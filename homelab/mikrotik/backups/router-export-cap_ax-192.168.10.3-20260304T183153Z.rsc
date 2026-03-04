# 1970-01-18 20:43:50 by RouterOS 7.11.2
# software id = 402I-BJZM
#
# model = cAPGi-5HaxD2HaxD
# serial number = HER095X5ZKZ
/interface bridge
add name=br-ap protocol-mode=none vlan-filtering=yes
/interface vlan
add interface=br-ap name=vlan10-mgmt vlan-id=10
/interface wifiwave2 security
add authentication-types=wpa2-psk,wpa3-psk name=sec-hivemind wps=disable
/interface wifiwave2 configuration
add name=cfg-hivemind security=sec-hivemind ssid=HiveMind
/interface wifiwave2
set [ find default-name=wifi1 ] configuration=cfg-hivemind disabled=no
set [ find default-name=wifi2 ] configuration=cfg-hivemind disabled=no
/interface bridge port
add bridge=br-ap comment=\
    "TRUNK uplink (tagged VLAN10 mgmt + tagged VLAN100 clients)" frame-types=\
    admit-only-vlan-tagged interface=ether1
add bridge=br-ap comment="HiveMind clients VLAN100" frame-types=\
    admit-only-untagged-and-priority-tagged interface=wifi1 pvid=100
add bridge=br-ap comment="HiveMind clients VLAN100" frame-types=\
    admit-only-untagged-and-priority-tagged interface=wifi2 pvid=100
/interface bridge vlan
add bridge=br-ap tagged=br-ap,ether1 vlan-ids=10
add bridge=br-ap tagged=br-ap,ether1 untagged=wifi1,wifi2 vlan-ids=100
/ip address
add address=192.168.10.3/24 comment="cAP ax mgmt (VLAN10 tagged)" interface=\
    vlan10-mgmt network=192.168.10.0
/ip dns
set servers=192.168.10.5
/ip route
add comment="Default GW" distance=1 dst-address=0.0.0.0/0 gateway=\
    192.168.10.1
/system identity
set name=capax
/system note
set show-at-login=no
