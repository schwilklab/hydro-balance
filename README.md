serial-balance
==============

Communicate with analytical balance.

See the config.ini file for settings.

`sbalance.py` supports two mode currently: a simple mass logging mode (with the update interval set in the config file) or a mode which prints running averages of flow rates used for measuring hydraulic conductance. Choose "mode = log" or "mode = "hydro".

Code currently supports serial communication with Metler balances and with Denver Instruments balances. Set the type as "model = Denver" or "model = Metler" in the config file. Also make sure that the com port and baud rate are set correctly in the config file. The code assumes 8-N-1 (8 data bits, no parity bit and 1 stop bit) -- this may have to be set on the balance interface. For example, our Metler analytical balance had different defaults and baud and bit settings had to be set using the balance menus.
