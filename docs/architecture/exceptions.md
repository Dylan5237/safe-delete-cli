# Accepted architecture exceptions

## P2: same-UID staging publication

- Decision: [`EXCEPTION ACCEPT`](https://github.com/Dylan5237/safe-delete-cli/issues/12#issuecomment-5699696980)
- Scope: Phase 2 only
- Accepted: 2026-09-16

Phase 2 excludes concurrent processes running as the same UID that can rename
or replace entries inside the private restore staging directory. The supported
model covers ordinary operation and concurrent pathname occupation in the
destination/shared tree, but does not claim isolation from same-UID mutation of
private staging entries.

The accepted residual risk is a false `restored` result and payload
misplacement if a private staging pathname is replaced at publication under
that excluded model. The private-staging design still closes the designated
shared-tree creation and cleanup windows; this exception does not claim the
remaining identity gap is fixed.
