# FranticDave Internet Monitor

A lightweight Raspberry Pi internet connection monitor.

## Current version

The first version checks internet connectivity at regular intervals, declares an outage only after a configurable threshold, records the outage start and recovery time, and writes completed outages to CSV.

## Planned additions

- Google Drive configuration
- Google Drive outage logging
- Email alerts when an outage is confirmed and when service returns
- Automatic startup as a systemd service
- Simple install and update scripts

## Target hardware

Designed for Raspberry Pi OS on Raspberry Pi 5 and Raspberry Pi Zero 2 W.
