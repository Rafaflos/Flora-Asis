# Entrenamiento de «Oye Flora»

Scripts de trabajo con los que se generó `desktop-node/models/oye_flora.onnx`. No son una
herramienta pulida: asumen las voces de Piper en `voices/` y los datos en `data/`.

1. `OYE=1 python gen.py 400 400 30` y `OYE=1 python gen2.py`: voz sintética con Piper
   (voces en español y voces multi-hablante con fonemas del español).
2. `python build.py 3`: ruido, eco y cambio de velocidad; extrae las características de openWakeWord.
3. `OYE=1 DIM=96 PEN=30 STEPS=12000 python train.py "" oye_flora.onnx`: entrena y exporta.
   Con `es_MX-ald,HELD` como primer argumento deja esas voces fuera para medir.
4. `OYE=1 python eval_stream.py modelo.onnx es_MX-ald-medium`: prueba en audio continuo.

Negativos de audio real: `validation_set_features.npy` y los primeros 1.5 GB de
`openwakeword_features_ACAV100M_2000_hrs_16bit.npy` (Hugging Face, davidscripka/openwakeword_features).
