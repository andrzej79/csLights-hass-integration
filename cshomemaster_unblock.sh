#!/bin/sh

sudo iptables -D OUTPUT -p tcp --dport 19468 -j REJECT

