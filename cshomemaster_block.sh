#!/bin/sh

sudo iptables -A OUTPUT -p tcp --dport 19468 -j REJECT

