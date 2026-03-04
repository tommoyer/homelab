# 1970-01-18 20:43:37 by RouterOS 7.11.2
# software id = WASL-UVIR
#
# model = CRS326-24G-2S+
# serial number = HEG08ZG4MJA
/interface bridge
add name=br-sw protocol-mode=none vlan-filtering=yes
/interface vlan
add interface=br-sw name=vlan10-mgmt vlan-id=10
/interface wireless security-profiles
set [ find default=yes ] supplicant-identity=MikroTik
/ip hotspot profile
set [ find default=yes ] html-directory=hotspot
/port
set 0 name=serial0
/interface bridge port
add bridge=br-sw comment="TRUNK uplink to hEX S (tag 10/20/30/100)" \
    frame-types=admit-only-vlan-tagged interface=ether1
add bridge=br-sw comment="ACCESS VLAN100" frame-types=\
    admit-only-untagged-and-priority-tagged interface=ether2 pvid=100
add bridge=br-sw comment="ACCESS VLAN100" frame-types=\
    admit-only-untagged-and-priority-tagged interface=ether3 pvid=100
add bridge=br-sw comment="ACCESS VLAN100" frame-types=\
    admit-only-untagged-and-priority-tagged interface=ether4 pvid=100
add bridge=br-sw comment="ACCESS VLAN100" frame-types=\
    admit-only-untagged-and-priority-tagged interface=ether5 pvid=100
add bridge=br-sw comment="ACCESS VLAN100" frame-types=\
    admit-only-untagged-and-priority-tagged interface=ether6 pvid=100
add bridge=br-sw comment="ACCESS VLAN100" frame-types=\
    admit-only-untagged-and-priority-tagged interface=ether7 pvid=100
add bridge=br-sw comment="ACCESS VLAN100" frame-types=\
    admit-only-untagged-and-priority-tagged interface=ether8 pvid=100
add bridge=br-sw comment="ACCESS VLAN100" frame-types=\
    admit-only-untagged-and-priority-tagged interface=ether9 pvid=100
add bridge=br-sw comment="ACCESS VLAN100" frame-types=\
    admit-only-untagged-and-priority-tagged interface=ether10 pvid=100
add bridge=br-sw comment="ACCESS VLAN100" frame-types=\
    admit-only-untagged-and-priority-tagged interface=ether11 pvid=100
add bridge=br-sw comment="ACCESS VLAN100" frame-types=\
    admit-only-untagged-and-priority-tagged interface=ether12 pvid=100
add bridge=br-sw comment="ACCESS VLAN100" frame-types=\
    admit-only-untagged-and-priority-tagged interface=ether13 pvid=100
add bridge=br-sw comment="ACCESS VLAN100" frame-types=\
    admit-only-untagged-and-priority-tagged interface=ether14 pvid=100
add bridge=br-sw comment="ACCESS VLAN100" frame-types=\
    admit-only-untagged-and-priority-tagged interface=ether15 pvid=100
add bridge=br-sw comment="ACCESS VLAN100" frame-types=\
    admit-only-untagged-and-priority-tagged interface=ether16 pvid=100
add bridge=br-sw comment="TRUNK homelab (tag 10/20/30)" frame-types=\
    admit-only-vlan-tagged interface=ether17
add bridge=br-sw comment="TRUNK homelab (tag 10/20/30)" frame-types=\
    admit-only-vlan-tagged interface=ether18
add bridge=br-sw comment="TRUNK homelab (tag 10/20/30)" frame-types=\
    admit-only-vlan-tagged interface=ether19
add bridge=br-sw comment="TRUNK homelab (tag 10/20/30)" frame-types=\
    admit-only-vlan-tagged interface=ether20
add bridge=br-sw comment="TRUNK homelab (tag 10/20/30)" frame-types=\
    admit-only-vlan-tagged interface=ether21
add bridge=br-sw comment="TRUNK homelab (tag 10/20/30)" frame-types=\
    admit-only-vlan-tagged interface=ether22
add bridge=br-sw comment="TRUNK homelab (tag 10/20/30)" frame-types=\
    admit-only-vlan-tagged interface=ether23
add bridge=br-sw comment="TRUNK homelab (tag 10/20/30)" frame-types=\
    admit-only-vlan-tagged interface=ether24
/interface bridge vlan
add bridge=br-sw tagged="br-sw,ether1,ether17,ether18,ether19,ether20,ether21,\
    ether22,ether23,ether24" vlan-ids=10
add bridge=br-sw tagged="br-sw,ether1,ether17,ether18,ether19,ether20,ether21,\
    ether22,ether23,ether24" vlan-ids=20
add bridge=br-sw tagged="br-sw,ether1,ether17,ether18,ether19,ether20,ether21,\
    ether22,ether23,ether24" vlan-ids=30
add bridge=br-sw tagged=br-sw,ether1 untagged="ether2,ether3,ether4,ether5,eth\
    er6,ether7,ether8,ether9,ether10,ether11,ether12,ether13,ether14,ether15,e\
    ther16" vlan-ids=100
/ip address
add address=192.168.10.2/24 comment="CRS mgmt" interface=vlan10-mgmt network=\
    192.168.10.0
/ip dns
set servers=192.168.10.5
/ip route
add comment="Default GW" distance=1 dst-address=0.0.0.0/0 gateway=\
    192.168.10.1
/system identity
set name=crs
/system note
set show-at-login=no
/system routerboard settings
set boot-os=router-os
/system swos
set allow-from-ports=p24,p25,p26 allow-from-vlan=100 identity=Switch \
    static-ip-address=192.168.100.3
