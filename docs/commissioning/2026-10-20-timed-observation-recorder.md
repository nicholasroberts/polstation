# Timed observation recorder commissioning — 2026-10-20

## Scope

Commissioned the initial immutable, software-parallel, three-camera Mono12
recorder on the Raspberry Pi 5 using release `a36ffad`. The deployed capture
policy was fixed 15 ms exposure, one observation per ten-minute UTC-aligned
slot, three attempts maximum, and 30,000,000 bytes/s per camera. Automatic
exposure remained explicitly unvalidated for scientific recording.

## Controlled one-shot result

The one-shot capture completed on its first attempt. All three Mako G-223B
cameras returned complete 2048 × 1088 Mono12 buffers of 4,456,448 bytes. The
request span was 0.937 ms. Each stored raw file matched its manifest SHA-256,
the effective configuration was preserved, and the latest BME280/EPEVER
snapshot was available. The manifest correctly retained synchronization as
`software-parallel-unverified`.

## Scheduled result

The recorder published a waiting state for the 13:40:00 UTC slot and completed
observation `obs-20261020T134000.017741Z-4246db67`. It then scheduled the next
slot for 13:50:00 UTC. Two observations occupied approximately 26 MiB, consistent
with about 12.75 MiB of raw camera data per observation before metadata and
filesystem overhead. At a ten-minute cadence this is approximately 1.8 GiB/day;
one-year storage is not commissioned on the Pi's current card.

## Camera-ownership handover finding

The first systemd recorder process raced the diagnostic camera-preview service
during handover. Vimba reported that camera 1 offered read access only, followed
by a process exit with `SIGSEGV`. The configured systemd restart recovered ten
seconds later and the scheduled observation completed, but crash recovery is not
an acceptable normal handover path.

The recorder unit originally declared
`Conflicts=polstation-camera-preview.service`, but `Conflicts=` alone does not
order the stop and start jobs. The unit now also orders itself relative to the
camera-preview service so systemd completes the conflicting stop before starting
the recorder. This change is covered by a deployment regression test.

Release `ea58084` then passed the repeat Pi handover test. The journal showed the
camera-preview service fully deactivated before the recorder was started. The
recorder opened all cameras, published `waiting` for the 13:50 UTC slot, and
reported `NRestarts=0`, `Result=success`, and no error. There was no Vimba access
failure, segmentation fault, or recovery restart.

## Remaining boundaries

- Decide and commission the field exposure-control policy; fixed 15 ms is only
  suitable for this test and shared automatic exposure remains scientifically
  unvalidated.
- Measure exposure synchronization rather than inferring it from the sub-
  millisecond software request span.
- Commission storage capacity, backup, power-loss recovery, disk-full behavior,
  and multi-day operation before unattended deployment.
