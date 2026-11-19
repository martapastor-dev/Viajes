#!/usr/bin/env python3
import json

M = json.load(open('/home/ubuntu/zonas_mask.json'))
CAR = json.load(open('/home/ubuntu/coche25.json'))
lats, lons, valid = M['lats'], M['lons'], M['valid']
nR, nC = len(lats), len(lons)

def rings(geom):
    if geom['type'] == 'Polygon': return geom['coordinates']
    return [r for p in geom['coordinates'] for r in p]

def in_poly(lat, lon, geom):
    # ray casting; un punto dentro si #cruces impar en un anillo exterior
    # y no está en un hueco
    polys = geom['coordinates'] if geom['type']=='MultiPolygon' else [geom['coordinates']]
    for poly in polys:
        inside = False
        ring = poly[0]
        j = len(ring)-1
        for i in range(len(ring)):
            xi, yi = ring[i][0], ring[i][1]
            xj, yj = ring[j][0], ring[j][1]
            if (yi > lat) != (yj > lat) and lon < (xj-xi)*(lat-yi)/(yj-yi)+xi:
                inside = not inside
            j = i
        if inside:
            hole = False
            for h in poly[1:]:
                j = len(h)-1; inn = False
                for i in range(len(h)):
                    xi, yi = h[i][0], h[i][1]
                    xj, yj = h[j][0], h[j][1]
                    if (yi > lat) != (yj > lat) and lon < (xj-xi)*(lat-yi)/(yj-yi)+xi:
                        inn = not inn
                    j = i
                if inn: hole = True; break
            if not hole: return True
    return False

geom = CAR['geometry']
zone = [[valid[r][c] and in_poly(lats[r], lons[c], geom) for c in range(nC)] for r in range(nR)]
nz = sum(map(sum, zone))
print(f'celdas finales: {nz}')

json.dump({'lats': lats, 'lons': lons, 'zone': zone, 'walk': M['walk'], 'tp': M['tp'], 'sta': M['sta']},
          open('/home/ubuntu/zona_final.json', 'w'))

# dibujar
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    z = np.array(zone, dtype=float)
    z[~np.array(valid)] = np.nan
    plt.figure(figsize=(10,10))
    for poly in (geom['coordinates'] if geom['type']=='MultiPolygon' else [geom['coordinates']]):
        rr = poly[0]
        plt.plot([p[0] for p in rr],[p[1] for p in rr],'r-',lw=1)
    plt.imshow(z, origin='lower', extent=[lons[0],lons[-1],lats[0],lats[-1]], cmap='Greens', alpha=.7)
    plt.plot([-3.8691104],[40.3930154],'r*',ms=15)   # CGS
    plt.plot([-3.69594],[40.42772],'b*',ms=15)       # Alonso Martínez
    plt.savefig('/home/ubuntu/zona.png',dpi=110,bbox_inches='tight')
    print('png ok')
except Exception as e:
    print('no plot:', e)
