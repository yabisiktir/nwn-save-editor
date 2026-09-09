# Bundled native `nwnsc`

Drop a **native** NWScript compiler here and the editor picks it up automatically —
no wine, nothing for the user to install. Used by the "Rescue item powers" wizard's
Tier-2 port. See `src/nwnsaveeditor/script_compiler.py` (`_find_bundled_nwnsc`).

## Where each binary goes

```
tools/
  macos/nwnsc          # Mach-O, native macOS build
  linux/nwnsc          # ELF, native Linux build
  windows/nwnsc.exe    # native Windows build
```

The editor loads the one matching the OS it is running on. Discovery order in
`find_compiler` is: `VK_NWNSC` env var → a `nwnsc` on `PATH` → **this bundled
binary** → wine (`nwnsc.exe` via CrossOver, macOS only, slow). A native binary is
far faster than wine, which pays a multi-second cold start on every compile.

## Getting a binary

A maintained cross-platform build is **nwneetools/nwnsc**
(<https://github.com/nwneetools/nwnsc>) — the same compiler Beamdog ships, built
natively for each OS. Download the release for the target platform, unzip, and place
the executable at the path above. On macOS/Linux the exec bit is restored at load
time if a packaging step drops it, and on a read-only app bundle a runnable copy is
staged in a temp dir.

## Packaging

`packaging/nwn-save-editor.spec` bundles `tools/<os>/` into the frozen app **only
when a binary for that OS is present**, so an empty tree is harmless. Binaries are
OS-specific and sizable — commit them deliberately (or fetch them in the build), not
by accident.
