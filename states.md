See `states.dot` for a state diagram of the system update script generated from
template file `updata_system_update.template.sh`. The states are defined by the
presence or absence of various empty stamp files. The table below defines the
exact relation.


Stamp file              | init | U | US | UR | UR2 | URF | UF | RF | FR | FR2 | FRF | done
------------------------|:----:|:-:|:--:|:--:|:---:|:---:|:--:|:--:|:--:|:---:|:---:|:----:
`update_started`        |  -   | X | X  | X  |  X  |  X  | X  | X  | X  |  X  |  X  | (X)
`update_done`           |  -   | - | X  | X  |  X  |  X  | -  | -  | -  |  -  |  -  | (X)
`update_failure`        |  -   | - | -  | -  |  -  |  -  | X  | X  | X  |  X  |  X  | (X)
`update_failure_again`  |  -   | - | -  | -  |  -  |  -  | -  | X  | -  |  -  |  -  | (X)
`update_reboot_started` |  -   | - | -  | X  |  X  |  X  | -  | -  | X  |  X  |  X  | (X)
`update_reboot_stderr`  |  -   | - | -  | -  |  X  |  X  | -  | -  | -  |  X  |  X  | (X)
`update_reboot_failed`  |  -   | - | -  | -  |  -  |  X  | -  | -  | -  |  -  |  X  | (X)
`update_finished`       |  -   | - | -  | -  |  -  |  -  | -  | -  | -  |  -  |  -  |  X


State **R** shown in diagram `states.dot` is the same as **FR2**, and state
**C** in the diagram is the same as **UR2**. Therefore, these are not listed in
the table above. In case the update script determines state **FR2** at startup,
it starts execution at state **R** in the diagram; correspondingly, if the
state is **UR2** at startup, the script starts at state **C**. Otherwise, the
script would end up in an infinite reboot loop.

The `done` state is kind of special as it depends only on the presence of the
`update_finished` file. That is, if this file is present, then no other stamp
files need to be considered.
