"""OCR one scanned page into a JSON list of text boxes. Usage: ocr_boxes.py <png> <out.json>"""
import json, sys
from rapidocr_onnxruntime import RapidOCR
ocr = RapidOCR()
res, _ = ocr(sys.argv[1])
boxes = []
for box, text, score in (res or []):
    xs = [p[0] for p in box]; ys = [p[1] for p in box]
    boxes.append({"x0": min(xs), "y0": min(ys), "x1": max(xs), "y1": max(ys), "text": text, "score": float(score)})
json.dump(boxes, open(sys.argv[2], "w"))
print(sys.argv[1], len(boxes), "boxes")
