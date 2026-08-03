# Baofeng UV-9R Autoconfig

Programador CLI y TUI para radios Baofeng UV-9R usando la librería CHIRP. Permite leer, importar, exportar y programar canales desde/hacia la radio.

## Tabla de Contenidos

- [Características](#características)
- [Stack](#stack)
- [Requisitos](#requisitos)
- [Instalación](#instalación)
- [Uso](#uso)
- [Formato CSV](#formato-csv)
- [Tests](#tests)
- [Licencia](#licencia)

## Características

- Interfaz dual: **CLI** (`cli.py`) y **TUI** (`tui.py` con Textual)
- Lectura/escritura de canales desde/hacia radio Baofeng UV-9R
- Importación/exportación de canales desde CSV
- Auto-detección del puerto serial mediante handshake
- Power-cycling automático para modo programación
- Respaldo de imagen de firmware
- Verificación de escritura

## Stack

- Python 3.11+
- [CHIRP](https://chirp.danplanet.com/) — drivers de radio
- [Textual](https://textual.textualize.io/) — framework TUI
- [pyserial](https://pyserial.readthedocs.io/) — comunicación serial

## Requisitos

- Python 3.11+
- CHIRP instalado (`apt install chirp` en Debian/Ubuntu)
- Cable de programación Baofeng
- Permisos sobre `/dev/ttyUSB*`

## Instalación

```bash
git clone https://github.com/bi0punk/baofeng_autoconfig.git
cd baofeng_autoconfig
pip install -r requirements.txt
sudo apt install chirp
```

## Uso

### CLI

```bash
# Listar puertos disponibles
python cli.py ports

# Leer canales de la radio y guardar en CSV
python cli.py read

# Escribir canales desde CSV a la radio
python cli.py write

# Exportar canales de la radio a CSV
python cli.py backup

# Especificar puerto
python cli.py --port /dev/ttyUSB1 read
```

### TUI

```bash
python tui.py
```

Navegación por teclado: `d` descargar, `u` subir, `i` importar CSV, `e` exportar CSV, `v` verificar.

## Formato CSV

```csv
Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,Mode,Power,Skip
1,Radio Uno,145.500,,0.6,,88.5,88.5,FM,5,
2,Radio Dos,146.000,-,0.6,Tone,88.5,88.5,FM,1,
```

| Columna | Descripción | Valores |
|---------|-------------|--------|
| Location | Número de canal (1-128) | Entero |
| Name | Nombre del canal | Texto |
| Frequency | Frecuencia en MHz | Float |
| Duplex | Modo duplex | `""`, `-`, `+`, `split` |
| Offset | Offset en MHz | Float |
| Tone | Modo de tono | `""`, `Tone`, `TSQL`, `DTCS`, `Cross` |
| rToneFreq | Frecuencia RX CTCSS | Float (ej: 88.5) |
| cToneFreq | Frecuencia TX CTCSS | Float |
| Mode | Modulación | `FM`, `NFM` |
| Power | Potencia en watts | `1`, `3`, `5` |
| Skip | Saltar canal | `""` o `S` |

## Tests

```bash
pip install pytest
pytest tests/ -v
```

## Licencia

MIT
