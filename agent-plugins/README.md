# EmuVista DSH development plugins

These packages live inside EmuVista and do not require a DSH source checkout. DSH dependencies are pinned to 0.2.0-rc.2.

| Package | Role |
| --- | --- |
| cloud-client | 23 authenticated Cloud file, share and recovery tools |
| cloud-bundle | emuvista-cloud-agent preset |
| claw | Cloud share/ETag observation, attention and followup wakeups |
| claw-bundle | Time Context, Schedule and Claw host plugins |

Bundles use relative link dependencies. The H14 topology imports package source through the SEED API and installs locked dependencies and compiles TypeScript during node image builds. Each agent has its own container filesystem; host node_modules and compiled output are not copied into images or shared between agents.

After editing source, regenerate the topology and rebuild the node images as described in the [H14 guide](../examples/H14_cloud_drive_service/README_zh.md). DSH profiles link to packages at /opt/emuvista/agent-plugins inside the container. The H14 topology declares first-time profile creation and bundle registration as container startup initialization, preserving existing profiles and user bundle choices. DSH startup remains an explicit manual command. Reloading Cloud or restarting DSH clears in-memory login credentials.

H14 is one example with two demonstration stages: stage one enables the Cloud bundle in the demo profile, and stage two enables Claw in that same profile. Both stages reuse the same topology, accounts and data.
