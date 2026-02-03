#!/bin/bash

# Run the rndc retransfer for each zone
echo "Retransferring DNS zones on BIND server..."
echo -n "XXXX"
ssh root@192.168.10.31 "rndc retransfer moyer.wtf"
echo -ne "\r✓XXX"
ssh root@192.168.10.31 "rndc retransfer 1.168.192.in-addr.arpa"
echo -ne "\r✓✓XX"
ssh root@192.168.10.31 "rndc retransfer 10.168.192.in-addr.arpa"
echo -ne "\r✓✓✓X"
ssh root@192.168.10.31 "rndc retransfer 20.168.192.in-addr.arpa"
echo -e "\r✓✓✓✓"

# Reload DNS on Hivemind Pihole
echo "Reloading DNS on Pihole servers..."
echo -n "XXX"
ssh root@192.168.1.4 "sudo pihole reloaddns"
echo -ne "\r✓XX"
# Reload DNS on Homelab Pihole
ssh root@192.168.10.27 "sudo pihole reloaddns"
echo -ne "\r✓✓X"
# Reload DNS on DMZ Pihole
ssh root@192.168.20.2 "sudo pihole reloaddns"
echo -ne "\r✓✓✓"