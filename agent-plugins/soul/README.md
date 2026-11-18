# Soul for DeepSeek Harness

[中文](README_zh.md)

Soul gives a DSH resident a configurable personality and a persistent store for experiences, relationship events, reflections, and intentions. These records belong to the resident and are available across sessions in the same DSH process.

Residents record observations or inferences with a source reference. A reflection cites saved evidence and may propose a wish. The resident can adopt that wish as an intention with a completion condition, then act through the tools available to its preset, defer the intention, or abandon it.

## Installation

Use Node.js 24, pnpm, and DSH 0.2.0-rc.2 with the Web session controller and DSH Schedule enabled. Run the build commands from this package directory in the environment where DSH will load the package.

```bash
DSH_PROFILE='your-profile-name'
pnpm install --frozen-lockfile
pnpm test
dsh plugin --profile "${DSH_PROFILE:?set DSH_PROFILE}" add "$(pwd)"
```

The package installs as a plugin dependency. In the profile's cordis.patch.yml, insert an entry with a unique id, set its name to @emuvista/soul, and supply the configuration below under config. If the profile already has a Soul entry, edit that entry. Use one resident per DSH process. Restart DSH after updating the profile and use the following command to check the composed configuration.

```bash
dsh --profile "${DSH_PROFILE:?set DSH_PROFILE}" --dump-config
```

Soul adds the personality card and current intentions through DSH runtime context. If the preset uses the persona plugin, enable includeRuntimeContext. When overriding a preset in a profile patch, preserve its full configuration because DSH replaces the config as a unit.

## Configuration and storage

| Field | Type | Meaning |
| --- | --- | --- |
| `residentId` | Required string | Stable identifier of 1–48 characters. Use letters, digits, underscores, or hyphens. |
| `card.identity` | Required string | A short description of the resident's identity. |
| `card.values` | Optional string array | Principles that guide the resident's choices. Defaults to an empty list. |
| `card.preferences` | Optional string array | The resident's usual preferences or approaches. Defaults to an empty list. |
| `card.boundaries` | Optional string array | Limits the resident should respect when deciding what to do. Defaults to an empty list. |
| `stateFile` | Optional path | Overrides the resident's state file location. |
| `autoReflection` | Optional boolean | Enables automatic reflection, defaults to true. |

The default state file is `$DSH_HOME/storages/emuvista-soul/<residentId>.json`. When DSH_HOME is unset, Soul uses `~/.dsh`. Use one writer per state file. Preserve the state file, DSH session data, and Schedule storage when replacing a container. Store credentials in the credential service and keep only relevant observations and references in Soul records.

## Automatic reflection

After a successful resident turn, Soul checks for at least three new saved experiences or relationship events. It sends up to eight recent new records and the resident card to the model selected for that session. The model chooses how many distinct concerns to propose, cites evidence for each, and assigns each an integer importance weight from 0 to 100. One to five is recommended when there are meaningful concerns. Soul saves them as candidate wishes and shows them in descending weight order, favoring newer concerns when weights tie. Older records without a weight appear at the neutral weight of 50. Existing weights on the previous 1–5 scale map to 0, 25, 50, 75, and 100. On a later review, the model may update, shelve, or restore an existing concern by ID. Each change records a reason, new evidence, and before-and-after values. Unmentioned concerns retain their values. Shelved concerns remain available for review. The resident can leave a wish alone or adopt it with `soul_intention_update`. Scheduling remains an explicit choice through `soul_rest`. Set `autoReflection: false` to avoid the additional model requests.

## Tools

| Tool | Purpose |
| --- | --- |
| `soul_recall` | Read current intentions and search recent experiences, relationship events, and reflections. |
| `soul_remember` | Record an experience or relationship event with a source and mark it as observed or inferred. |
| `soul_reflect` | Save a judgment citing existing experience or relationship records, with an optional candidate wish. |
| `soul_intention_update` | Adopt a wish as an intention, revise or pause an intention, or mark it completed or abandoned. |
| `soul_life` | Start or stop periodic opportunities for independent activity in the resident's home session. |
| `soul_rest` | Set or replace a one-time reminder for an active intention. |

## Resident lifecycle

Ask the resident to call `soul_life` with `enabled=true` in its home session to start periodic activity. The optional `interval_seconds` defaults to 120 and accepts integers from 60 to 86400. Each Schedule delivery gives the resident an opportunity to reflect, act on an intention, or wait. The resident chooses the goal and the action. Each delivery can invoke the configured model.

A resident can use `soul_rest` to schedule one follow-up for an active intention and specify what to reassess on waking. One Soul-managed follow-up is stored per resident. Pausing or closing its intention cancels the reminder. The periodic life cycle can wake the resident earlier, at which point it can decide to keep waiting.

Schedule handles delivery and recovery for both kinds of reminders. Reminders target the session that created them. To stop a resident's life cycle, ask it to call `soul_life` with `enabled=false`. This cancels the periodic task and any Soul follow-up owned by that session. An already queued reminder can still arrive. Before acting, the resident checks the current intention and world state.

## Verification

Run `pnpm test` for model-free checks of evidence validation, state reload, intention updates, and reminder management. To verify a deployed profile, check that the six tools are registered and that the runtime context contains the correct personality and current intentions. The trajectory can be used to verify which event woke the resident, what evidence it cited, and whether its actions and state changes refer to the same intention ID.

## Concern reviews and emotion

Set `concernReviewSeconds` (5–86400 seconds) with `autoReflection` enabled to let a pending concern trigger a background review. The resident first needs to complete a turn to establish a model route. Each review revisits one concern with its previously cited experiences and persists the successful review time. The resident can decide how to act in its own session.

Set `emotion.enabled: true` to expose worry, frustration, and joy on a 0–100 scale in context and through `soul_recall`. The resident calls `soul_appraise` with a saved experience or relationship event ID and a change from −100 to 100 per dimension. Each event applies once. On read, the persisted vector decays toward `baseline` according to `halfLifeSeconds`. The default baseline is zero in each dimension and the default half-life is 3600 seconds. The resident and the reflection model can consider the current emotion when evaluating the situation.

## Autonomous operation

With Soul installed, all agents in the host process are barred from requesting operator confirmation, approval or an answer. The tool runtime denies question tools and entry to or exit from interactive plan mode. The host rejects approval and question events. Authorized tools keep their existing permissions and operations requiring additional permission fail closed.

Soul filters common Chinese and English requests for confirmation before publishing model text. A matching text block is replaced. Soul can send at most one internal correction in the same turn, marked emuvista-soul-autonomy, so the agent can use existing permissions, choose another action or stop. Text filtering uses explicit phrasing. The structured approval and question paths are denied unconditionally.
