The existing PAPER epoch is recovered from its portfolio inception, canonical
portfolio journal/checkpoint, all native lane books/journals and genesis files,
pending delivery records, reservations, Survivor/pipeline/directional state and
shared finalized evidence/recovery state. These are AUTHORITATIVE. The complete
state directory is copied conservatively; unknown files default to authoritative.

`shared/robinhood-evidence.sqlite` is a REBUILDABLE_CACHE. Health, portfolio JSON,
inception JSON, and dashboard/acceptance JSON are READ_ONLY_PROJECTION. SQLite
WAL/SHM files, sockets and writer locks are EPHEMERAL: the SQLite backup API merges
committed WAL contents into each copied database; their physical files are not
restored. Provider pacing databases are retained conservatively as authoritative
recovery inputs. Their boot-relative queues are recovered by existing runtime
logic; restored queues cannot grant duplicate economic activity.

The systemd backup service pins the original volume/epoch, fences an inactive
supervisor or briefly freezes the complete running cgroup, copies every SQLite
database with the backup API, checks integrity and full replay identity, fsyncs
the completed point on the persistent volume, and thaws before snapshot creation.
ExecStopPost thaws after process loss. Active copies have a five-second deadline;
an incomplete copy never becomes a restore point. A DigitalOcean Volume snapshot
retains this coherent point outside the runtime host/storage failure domain.
Restore the completed point, not arbitrary concurrently changing volume files.

Daily backups retain three snapshots/points. The root-only DigitalOcean credential
is read only by maintenance. The PAPER service, observers and dashboard never
receive it. Backup/API failures cannot initialize or replace an epoch.

Restore verification uses a new isolated volume mounted read-only by its unique
DigitalOcean by-id device, then a disposable writable copy. Verify all retained
file hashes and SQLite integrity, the exact full portfolio replay, pending
deliveries, epoch, native IDs and sleeves. Replay twice on the isolated copy and
prove another writer is fenced. Never restore over the authoritative root.
Production startup pins the original volume device as well as filesystem UUID:
a snapshot clone with the same filesystem UUID cannot replace the expected volume.

The independent observer stores bounded host/process, provider, evidence, storage,
maintenance, portfolio and six-regime observations outside economic state.
The condition monitor distinguishes temporary self-healing from persistent owner
action. Its localhost metrics endpoint is read-only and consumed by the existing
DigitalOcean agent. The email rule is not verified merely by API creation: its
application metric must reach the alert evaluator. Missing external delivery
keeps G03 incomplete and prevents acceptance candidate freeze.

Durable acceptance uses `meme-machine-acceptance@PHASE.service`, one shared flock,
and ordinary status/results/logs under `/var/lib/meme-machine-acceptance`. Source,
environment, storage configuration and epoch measurements must agree across all
phases. Required durations are 3600 and 129600 seconds; short or interrupted jobs
cannot pass. Observation and acceptance cannot write economic state. Only the
explicit RECOVERY test can signal the owned PAPER processes.
