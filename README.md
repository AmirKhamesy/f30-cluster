# F30 Cluster

Drive a real BMW F30 instrument cluster from Assetto Corsa.

Speed, RPM, gear, fuel, blinkers, headlights and backlight all work.

Only tested with Assetto Corsa.

## Demo

https://github.com/user-attachments/assets/4ea559b4-0181-4aa8-b294-78ec7f7430af

## What you need

- BMW F30 instrument cluster (tested with a 6WA)
- Power supply (tested with a regulated 13.8 V supply)
- USB-CAN adapter (tested with a candleLight)
- Assetto Corsa with Custom Shaders Patch (CSP)
- Python 3.9+

## Wiring

| Cluster pin | Wire colour    | Connect to        |
| ----------- | -------------- | ----------------- |
| 1           | red / brown    | PSU +             |
| 2           | red            | PSU +             |
| 11          | red / green    | PSU +             |
| 7           | yellow / brown | PSU −             |
| 8           | brown          | PSU −             |
| 6           | blue / red     | candleLight CAN H |
| 12          | red            | candleLight CAN L |

## Setup

```
pip install -r requirements.txt
```

Copy the `F30Cluster` folder into `assettocorsa/apps/lua/`.

## Run

Power on the cluster and run:

```
python f30_cluster.py
```

Press Ctrl+C to stop.

## Credits

- https://github.com/r00li/CarCluster
- https://github.com/fatihcesur/bmw-f30-cluster-simhub
