#!/bin/sh
# Makes the SQLite data directory writable and drops privileges, working across
# every deployment shape without the operator having to configure anything.
#
# The app opens a SQLite database under /data, so that directory must be
# writable by whatever uid the app ends up running as. Getting there differs by
# how /data was provided:
#
#   * Docker named volume      - Docker seeds it from the image, already ours.
#   * Bind mount, Linux fs     - chown it (we start as root by default).
#   * Bind mount, CIFS/SMB/NFS - chown is refused or a silent no-op, because
#                                ownership comes from the mount options. The
#                                only way to write there is to *be* the uid the
#                                share is mounted as.
#   * Hardened runtime         - Kubernetes runAsUser/runAsNonRoot already
#                                picked a uid and we can't chown or gosu at all.
#
# So rather than demanding a specific uid, this resolves the first uid that can
# actually write, in order of preference, and only fails when no uid can (a
# genuinely read-only mount, which no configuration can fix).
#
# PUID/PGID override the whole thing. Setting them explicitly is a deliberate
# choice, so it's honoured exactly and fails loudly rather than being silently
# second-guessed.
set -e

DEFAULT_UID=10001   # appuser, created in the Dockerfile
DEFAULT_GID=999     # app

# The image sets PUID/PGID as ENV defaults, so "did the operator choose this?"
# can't be answered by emptiness alone - compare against the known defaults.
PUID_EXPLICIT=""
[ "${PUID:-$DEFAULT_UID}" = "$DEFAULT_UID" ] || PUID_EXPLICIT=1
[ "${PGID:-$DEFAULT_GID}" = "$DEFAULT_GID" ] || PUID_EXPLICIT=1
PUID="${PUID:-$DEFAULT_UID}"
PGID="${PGID:-$DEFAULT_GID}"

# Probe the directory the app will really use, not a hardcoded /data, so this
# stays honest when DATABASE_PATH points elsewhere.
DB_PATH="${DATABASE_PATH:-/data/healthcheck.db}"
DB_DIR="$(dirname "$DB_PATH")"

# True if uid:gid can create a file in DB_DIR. An actual write, not a mode
# inspection - only a real touch accounts for NFS squashing, read-only mounts,
# ACLs and friends.
can_write_as() {
    _probe="$DB_DIR/.write-probe.$$"
    if [ "$(id -u)" = "0" ]; then
        gosu "$1:$2" sh -c "touch '$_probe' 2>/dev/null && rm -f '$_probe' && echo yes" 2>/dev/null || true
    else
        sh -c "touch '$_probe' 2>/dev/null && rm -f '$_probe' && echo yes" 2>/dev/null || true
    fi
}

fail_unwritable() {
    _uid="$1"
    _owner=$(stat -c '%u:%g' "$DB_DIR" 2>/dev/null || echo 'unknown')
    _mode=$(stat -c '%a' "$DB_DIR" 2>/dev/null || echo 'unknown')
    echo "FATAL: $DB_DIR is not writable by uid $_uid." >&2
    echo "       It is owned by $_owner with mode $_mode." >&2
    echo "" >&2

    if [ "$(id -u)" != "0" ]; then
        # Started non-root (docker run --user, compose `user:`, Portainer's
        # User field, Kubernetes runAsUser). We can neither chown nor switch
        # user from here, so PUID/PGID and named volumes are NOT the fix and
        # suggesting them just sends people in circles - this is host-side.
        echo "  This container was started as a non-root user, so it cannot take" >&2
        echo "  ownership of the directory itself. Fix one of these on the host:" >&2
        echo "" >&2
        echo "    * Make the directory match the uid you are running as:" >&2
        echo "        chown -R $_uid:$(id -g) <host path>" >&2
        echo "    * Or drop the user override (remove \`user:\` from compose /" >&2
        echo "      clear the User field / omit --user) and let the container" >&2
        echo "      fix ownership itself on startup." >&2
        echo "    * Note: PUID/PGID have no effect here - they only apply when" >&2
        echo "      the container starts as root." >&2
    else
        echo "  The directory could not be chowned and no usable uid was found;" >&2
        echo "  this usually means the volume is mounted read-only." >&2
        echo "" >&2
        echo "  Fix one of these, then restart the container:" >&2
        echo "    * Remove any :ro flag from the volume mount." >&2
        echo "    * Bind mount on a normal Linux filesystem:" >&2
        echo "        chown -R $DEFAULT_UID:$DEFAULT_GID <host path>" >&2
        echo "    * Bind mount on CIFS/SMB or NFS:" >&2
        echo "        set PUID/PGID to the uid/gid the share is mounted as," >&2
        echo "        e.g. -e PUID=1000 -e PGID=1000" >&2
        echo "    * Simplest: use a Docker named volume instead of a bind mount," >&2
        echo "        e.g. -v tailscale-healthcheck-data:/data" >&2
    fi
    exit 1
}

if [ ! -d "$DB_DIR" ]; then
    # Only reachable when DATABASE_PATH points somewhere unmounted; /data
    # itself is created in the image.
    if [ "$(id -u)" = "0" ]; then
        mkdir -p "$DB_DIR" 2>/dev/null || true
    fi
    if [ ! -d "$DB_DIR" ]; then
        echo "FATAL: database directory $DB_DIR does not exist and could not be created." >&2
        echo "       Mount a volume there, or point DATABASE_PATH at an existing path." >&2
        exit 1
    fi
fi

# Already non-root (Kubernetes runAsUser, docker run --user, rootless): we
# can neither chown nor switch user, so this uid is the only candidate.
if [ "$(id -u)" != "0" ]; then
    [ "$(can_write_as "$(id -u)" "$(id -g)")" = "yes" ] || fail_unwritable "$(id -u)"
    exec "$@"
fi

# Best effort; expected to fail on CIFS/NFS, which is not fatal on its own.
chown -R "$PUID:$PGID" "$DB_DIR" 2>/dev/null || true

if [ -n "$PUID_EXPLICIT" ]; then
    # Explicitly configured: honour it exactly, or fail - never silently run as
    # a different user than the operator asked for.
    [ "$(can_write_as "$PUID" "$PGID")" = "yes" ] || fail_unwritable "$PUID"
    exec gosu "$PUID:$PGID" "$@"
fi

# Defaults in play: find the first uid that can actually write.
if [ "$(can_write_as "$PUID" "$PGID")" = "yes" ]; then
    exec gosu "$PUID:$PGID" "$@"
fi

# The chown didn't take (CIFS/SMB/NFS). Adopt whoever does own the directory -
# on those mounts that's precisely the uid the share was mounted as.
OWNER_UID=$(stat -c '%u' "$DB_DIR" 2>/dev/null || echo '')
OWNER_GID=$(stat -c '%g' "$DB_DIR" 2>/dev/null || echo '')
if [ -n "$OWNER_UID" ] && [ "$OWNER_UID" != "0" ] && [ "$(can_write_as "$OWNER_UID" "$OWNER_GID")" = "yes" ]; then
    echo "NOTE: could not take ownership of $DB_DIR (expected on CIFS/SMB and NFS mounts)." >&2
    echo "      Running as its existing owner $OWNER_UID:$OWNER_GID instead." >&2
    echo "      Set PUID/PGID explicitly to override this." >&2
    exec gosu "$OWNER_UID:$OWNER_GID" "$@"
fi

# Last resort: the directory is root-owned and closed to everyone else, and we
# couldn't chown it. Staying root is worse for isolation but is the difference
# between running and a crash loop, so warn loudly rather than refuse.
if [ "$(can_write_as 0 0)" = "yes" ]; then
    echo "WARNING: $DB_DIR is writable only by root and its ownership could not be changed." >&2
    echo "         Continuing as root - this gives up the container's privilege dropping." >&2
    echo "         To fix: chown -R $DEFAULT_UID:$DEFAULT_GID <host path>, or set PUID/PGID." >&2
    exec "$@"
fi

fail_unwritable "$PUID"
