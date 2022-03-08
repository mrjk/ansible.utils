# MrJK Ansible utilities

This collection provides some useful plugins for ansible:

* Inventory Plugins
  * `exclude`: Exclude hosts or groups from inventory. This allow to ignore hosts in maintenance mode.
  * `include`: Include other inventory source files. This avoid usage of symlinks.
  * `terraform`: Allow to load inventory from terraform state. Supports local and consul backends.
* Filter Plugins
  * Work In Progress

