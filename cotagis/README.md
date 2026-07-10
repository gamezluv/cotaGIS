# CotaGIS (plugin de QGIS) — v1.1

Acotado (dimensionamiento) de **líneas y polígonos** al estilo de los comandos **DIM de AutoCAD**, con **Object Snap** magnético y estilos configurables.

## Tipos de cota (Dimension Types)

Botón desplegable en la barra de herramientas (todos con snap y vista previa):

| Tipo | Equivalente AutoCAD | Clics |
|---|---|---|
| Cota lineal (H/V automática según arrastre) | `DIMLINEAR` | P1, P2, posición |
| Cota alineada | `DIMALIGNED` | P1, P2, posición |
| Cota continua (encadenada) | `DIMCONTINUE` | P1, P2, posición, Pn… (clic derecho termina) |
| Cota en línea base (apilada desde la base) | `DIMBASELINE` | P1, P2, posición, Pn… (clic derecho termina) |
| Cota angular (arco con flechas y grados) | `DIMANGULAR` | vértice, lado 1, lado 2, posición del arco |
| Cota radial (`R = …`, cruz en el centro) | `DIMRADIUS` | centro, punto de la curva |
| Cota diametral (`Ø = …`) | `DIMDIAMETER` | dos puntos opuestos del círculo |
| Cota de longitud de arco (`⌒ …`) | `DIMARC` | inicio, punto intermedio, fin del arco |
| Cota de coordenadas (`E = … N = …`) | `DIMORDINATE` | punto, posición de la etiqueta |

Además, **Acotar capa…** genera de golpe todas las cotas alineadas de los lados de una capa (más área, perímetro/longitud total y ángulos internos).

## Object Snap (OSNAP)

El cursor se atrae magnéticamente —con marcador magenta— a referencias de **todas las capas visibles**, dentro de un radio de tolerancia en píxeles. En **Configuración… ⚙** eliges cuáles activar:

- Vértice · Extremo de línea · Punto medio de segmento · Punto más cercano en segmento · Centroide · Interior de área · **Intersección**
- Radio de tolerancia configurable (px)

## Estilos configurables

- **Extension lines**: mostrar/ocultar, separación del objeto (gap) y sobrepaso (overshoot), en unidades de mapa (0 = automático).
- **Arrowheads**: tick arquitectónico 45°, flecha abierta, flecha rellena, punto, o ninguno; tamaño configurable.
- **Formato**: separación de la cota, altura de texto (unid. de mapa, como en CAD), decimales, sufijo de unidades y espaciado de línea base.

La configuración se guarda entre sesiones (QgsSettings).

## Salida

Las cotas se crean como capas de memoria estilizadas en el grupo *«Cotas (CotaGIS)»* (líneas, textos etiquetados con rotación, y flechas rellenas como polígonos). Exporta a GeoPackage/Shapefile para conservarlas. Las medidas se calculan con el elipsoide del proyecto.

**Recomendado:** CRS proyectado (p. ej. `EPSG:32718` — UTM 18S para Lima) para que separaciones y textos estén en metros.

## Instalación manual

*Complementos → Administrar e instalar complementos → Instalar a partir de ZIP*.

## Publicación en plugins.qgis.org

1. Edita `metadata.txt`: reemplaza `email`, `homepage`, `tracker` y `repository` con tus datos reales (el portal exige `repository` y `tracker` válidos).
2. Sube el ZIP con tu cuenta OSGeo en *Upload a plugin*. El ZIP ya cumple: una sola carpeta `cotagis` en la raíz, sin `.pyc`, con `LICENSE` GPL-3.

## Licencia

GNU GPL v3 o posterior. Ver `LICENSE`.
