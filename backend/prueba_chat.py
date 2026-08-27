from rag_engine.buscador import hacer_pregunta

pregunta = "¿De qué trata la Norma Chilena NCh2485 y qué instituto la preparó?"
respuesta = hacer_pregunta(pregunta)

print("\n--- RESPUESTA DE LA IA ---")
print(respuesta)
print("--------------------------")