# UpdaTA, the T+A Update Daemon

## Copyright and contact

UpdaTA is released under the terms of the GNU General Public License version 3
(GPLv3). See file <tt>COPYING</tt> for licensing terms.

Contact:

    T+A elektroakustik GmbH & Co. KG
    Planckstrasse 11
    32052 Herford
    Germany

## Short description

_updata_ is software for managing and running system updates using the system's
package manager. In particular, it is used for
- managing package repository configuration;
- initiating system updates;
- making sure a running update is performed completely even if multiple reboots
  are required;
- making sure a running update is performed completely even if the system is
  powered off or crashes in the middle of updating,
- making sure a failed update is either rolled back or the system is rebooted
  into recovery mode.
