#!/usr/bin/env python2.6
"""
    This file is part of a toolset to manipulate LISP control-plane
    packets "py-lispnetworking".

    Copyright (C) 2011 Marek Kuczynski <marek@intouch.eu>
    Copyright (C) 2011 Job Snijders <job@intouch.eu>

    This file is subject to the terms and conditions of the GNU General
    Public License. See the file COPYING in the main directory of this
    archive for more details.
"""


import scapy,socket,struct
from scapy import *
from scapy.all import *

"""  GENERAL DECLARATIONS """

_LISP_TYPES = { 
    0 : "reserved", 
    1 : "maprequest", 
    2 : "mapreply", 
    3 : "mapregister", 
    4 : "mapnotify", 
    8 : "encapsulated_control_message" 
}

_LISP_MAP_REPLY_ACTIONS = {
    0 : "no_action",
    1 : "native_forward",
    2 : "send_map_request",
    3 : "drop"
}

_AFI = {
    """ An AFI value of 0 used in this specification indicates an unspecified encoded address where the length of the address is 0 bytes following the 16-bit AFI value of 0. See the following URL for the other values:
    http://www.iana.org/assignments/address-family-numbers/address-family-numbers.xml """

    "zero" : 0,
    "ipv4" : 1,
    "ipv6" : 2,
    "lcaf" : 16387 
}

"""CLASS TO DETERMINE WHICH PACKET TYPE TO INTERPRET
scapy is designed to read out bytes before it can call another class. we are using the ugly conditional construction you see below to circumvent this, since all classes must have the length of one or more bytes. improving and making this prettier is still on the TODO list """


class LISP_Type(Packet):
    """ first part of any lisp packet, in this class we also look at which flags are set
    because scapy demands certain bit alignment. A class must contain N times 8 bit, in our case 16. """
    name = "LISP packet type and flags"
    fields_desc = [
    BitEnumField("packettype", 0, 4, _LISP_TYPES),
    	# request flag fields, followed by 6 pad fields
	ConditionalField(FlagsField("request_flags", None, 6, ["authoritative", "map_reply_included", "probe", "smr", "pitr", "smr_invoked"]), lambda pkt:pkt.packettype==1),
	ConditionalField(BitField("p1", 0, 6), lambda pkt:pkt.packettype==1),
	    # reply flag fields, followed by 9 padding bits
	ConditionalField(FlagsField("reply_flags", None, 3, ["probe", "echo_nonce_alg", "security" ]), lambda pkt:pkt.packettype==2),
	ConditionalField(BitField("p2", 0, 9), lambda pkt:pkt.packettype==2),
	    # register flag fields, with 18 padding bits in between	
	ConditionalField(FlagsField("register_flags", None, 1, ["proxy_map_reply"]), lambda pkt:pkt.packettype==3),
	ConditionalField(BitField("p3", 0, 18), lambda pkt:pkt.packettype==3),
    	ConditionalField(FlagsField("register_flags", None, 1, ["want-map-notify"]), lambda pkt:pkt.packettype==3),
	    # notify packet reserved fields
	ConditionalField(BitField("p4", 0, 12), lambda pkt:pkt.packettype==4),
	    # encapsulated packet flag fields, the flag gets read and passed back to the IP stack (see bindings)	
	ConditionalField(FlagsField("ecm_flags", None, 1, ["security"]), lambda pkt:pkt.packettype==8),
	ConditionalField(BitField("p8", 0, 27), lambda pkt:pkt.packettype==8)
        ]

""" the class below reads the first byte of an unidentified IPv4 or IPv6 header. it then checks the first byte of the payload to see if its IPv4 or IPv6 header. the IPv4 header contains a byte to describe the IP version, which is always hex45. IPv6 has a 4 bit header, which is harder to read in scapy. maybe this can be done in a prettier way - TODO """

class Version(Packet):
    def guess_payload_class(self, payload):
        if payload[:1] == "\x45":
            return IP
        else:
            return IPv6

""" 
    LISPAddressField, Dealing with addresses in LISP context, the packets often contain (afi, address) where the afi decides the length of the address (0, 32 or 128 bit). LISPAddressField will parse an IPField or an IP6Field depending on the value of the AFI field. 
    
"""

class LISP_AddressField(Field):
    def __init__(self, fld_name, ip_fld_name):
        Field.__init__(self, ip_fld_name, None)
        
        self.fld_name=fld_name
        self._ip_field=IPField(ip_fld_name, "192.168.1.1")
        self._ip6_field=IP6Field(ip_fld_name, "2001:db8::1")

    def getfield(self, pkt, s):
        if getattr(pkt, self.fld_name) == _AFI["ipv4"]:
            return self._ip_field.getfield(pkt,s)
        elif getattr(pkt, self.fld_name) == _AFI["ipv6"]:
            return self._ip6_field.getfield(pkt,s)

    def addfield(self, pkt, s, val):
        if getattr(pkt, self.fld_name) == _AFI["ipv4"]:
            return self._ip_field.addfield(pkt, s, val)
        elif getattr(pkt, self.fld_name) == _AFI["ipv6"]: 
            return self._ip6_field.addfield(pkt, s, val)
            
"""RECORD FIELDS, PART OF THE REPLY, REQUEST, NOTIFY OR REGISTER PACKET CLASSES"""

""" LISP Address Field, used multiple times whenever an AFI determines the length of the IP field. for example, IPv4 requires 32 bits of storage while IPv6 needs 128 bits. This field can easily be extended once new LISP LCAF formats are needed, see the LISP_AddressField class for this. """
class LISP_AFI_Address(Packet):                     # used for 4 byte fields that contain a AFI and a v4 or v6 address
    name = "ITR RLOC Address"
    fields_desc = [
        ShortField("lispafi", 0),
        LISP_AddressField("lispafi", "lispaddress")
    ]


    def extract_padding(self, s):
        return "", s

""" Map Reply LOCATOR, page 28, paragraph 6.1.4, the LOCATOR appears N times dependant on the locator count in the record field """
class LISP_Locator_Record(Packet):
    name = "LISP Locator Records"
    fields_desc = [
        ByteField("priority", 0),
        ByteField("weight", 0),
        ByteField("multicast_priority", 0),
        ByteField("multicast_weight", 0),
        BitField("reserved", 0, 13),
        FlagsField("locator_flags", 0, 3, ["local_locator", "probe", "route"]), 
        ShortField("locator_afi", 0),
        LISP_AddressField("locator_afi", "locator_address")
    ]

    # delimits the packet, so that the remaining records are not contained as 'raw' payloads 
    def extract_padding(self, s):
        return "", s

""" Map Reply RECORD, page 28, paragraph 6.1.4, the RECORD appears N times dependant on Record Count """
class LISP_MapRecord(Packet):
    name = "LISP Map-Reply Record"
    overload_fields = { LISP_Type: { "eid_prefix_afi":1, "eid_prefix":'192.168.1.1' }}
    fields_desc = [
        BitField("record_ttl", 0, 32),
        FieldLenField("locator_count",  0, "locators", "B", count_of="locators"),
        ByteField("eid_prefix_length", 0),
        BitEnumField("action", 0, 3, _LISP_MAP_REPLY_ACTIONS),
        BitField("authoritative", 0, 1),
        BitField("reserved", 0, 16),
        BitField("map_version_number", 0, 12),
        ShortField("record_afi", 0),
        LISP_AddressField("record_afi", "record_address"),
        PacketListField("locators", None, LISP_Locator_Record, count_from=lambda pkt: pkt.locator_count)
    ]

    # delimits the packet, so that the remaining records are not contained as 'raw' payloads
    def extract_padding(self, s):
        return "", s

""" Map Request RECORD, page 25, paragraph 6.1.2, the 'REC', appears N times depending on record count """
class LISP_MapRequestRecord(Packet):
    name= "LISP Map-Request Record"
    fields_desc = [
        ByteField("reserved", 0),
	        # eid mask length
        ByteField("eid_mask_len", 0),
        	# eid prefix afi
        ShortField("request_afi", 0),
	        # eid prefix information + afi
        LISP_AddressField("request_afi", "request_address")
    ]
   
    def extract_padding(self, s):
        return "", s

"""PACKET TYPES (REPLY, REQUEST, NOTIFY OR REGISTER)"""

class LISP_MapRequest(Packet):
    """ map request part used after the first 16 bits have been read by the LISP_Type class"""
    name = "LISP Map-Request packet"
    fields_desc = [
            # Right now we steal 3 extra bits from the reserved fields that are prior to the itr_rloc_records
        FieldLenField("itr_rloc_count", 0, "itr_rloc_records", "B", count_of="itr_rloc_records", adjust=lambda pkt,x:x + 1),                          
        FieldLenField("request_count", 0, "request_records", "B", count_of="request_records", adjust=lambda pkt,x:x + 1),  
        XLongField("nonce", 0),
            # below, the source address of the request is listed, this occurs once per packet
        ShortField("source_afi", 0),
        # the LISP IP address field is conditional, because it is absent if the AFI is set to 0 - TODO
        ConditionalField(LISP_AddressField("source_afi", "source_address"), lambda pkt:pkt.source_afi != 0),
        PacketListField("itr_rloc_records", None, LISP_AFI_Address, count_from=lambda pkt: pkt.itr_rloc_count + 1),
        PacketListField("request_records", None, LISP_MapRequestRecord, count_from=lambda pkt: pkt.request_count + 1) 
    ]

class LISP_MapReply(Packet):                                                    
    """ map reply part used after the first 16 bits have been read by the LISP_Type class"""
    name = "LISP Map-Reply packet"
    fields_desc = [
        BitField("reserved", 0, 8),
        FieldLenField("map_count", 0, "map_records", "B", count_of="map_records", adjust=lambda pkt,x:x/16 - 1),  
        XLongField("nonce", 0),
        PacketListField("map_records", 0, LISP_MapRecord, count_from=lambda pkt:pkt.map_count + 1)
    ]

class LISP_MapRegister(Packet):
    """ map reply part used after the first 16 bits have been read by the LISP_Type class"""
    name = "LISP Map-Register packet"
    fields_desc = [ 
        FieldLenField("register_count", None, "register_records", "B", count_of="register_records", adjust=lambda pkt,x:x/16 - 1),
        XLongField("nonce", 0),
        ShortField("key_id", 0),
        ShortField("authentication_length", 0),
            # authentication length expresses itself in bytes, so no modifications needed here
        StrLenField("authentication_data", None, length_from = lambda pkt: pkt.authentication_length),
        PacketListField("register_records", None, LISP_MapRecord, count_from=lambda pkt:pkt.register_count + 1)
    ]

class LISP_MapNotify(Packet):
    """ map notify part used after the first 16 bits have been read by the LISP_Type class"""
    name = "LISP Map-Notify packet"
    fields_desc = [
        BitField("reserved", 0, 12),
        ByteField("reserved_fields", 0),
        FieldLenField("notify_count", None, "notify_records", "B", count_of="notify_records"),
        XLongField("nonce", 0),
        ShortField("key_id", 0),
        ShortField("authentication_length", 0),
            # authentication length expresses itself in bytes, so no modifications needed here
        StrLenField("authentication_data", None, length_from = lambda pkt: pkt.authentication_length),
        PacketListField("notify_records", None, LISP_MapRecord, count_from=lambda pkt: pkt.notify_count)
    ]

def sendLIGquery():
    """ trying to spawn a map request that can be answered by a mapserver """ """ WIP """
    return IP()/UDP(sport=4342,dport=4342)/LISP_Type()/LISP_MapRequest()

"""
Bind LISP into scapy stack

According to http://www.iana.org/assignments/port-numbers :
lisp-data       4341/tcp   LISP Data Packets
lisp-data       4341/udp   LISP Data Packets
lisp-cons       4342/tcp   LISP-CONS Control
lisp-control    4342/udp   LISP Data-Triggered Control
"""

    # tie LISP into the IP/UDP stack
bind_layers( UDP, LISP_Type, dport=4342 )
bind_layers( UDP, LISP_Type, sport=4342 )
bind_layers( LISP_Type, LISP_MapRequest, packettype=1 )
bind_layers( LISP_Type, LISP_MapReply, packettype=2 )
bind_layers( LISP_Type, LISP_MapRegister, packettype=3 )
bind_layers( LISP_Type, LISP_MapNotify, packettype=4 )
    # if an encapsulated packet shows up, rebind to the IP4 or IP6 stack - TODO
bind_layers( LISP_Type, Version, packettype=8 )

""" start scapy shell """
    # debug mode
if __name__ == "__main__":
    interact(mydict=globals(), mybanner="lisp debug")
