# Guía de grabación del conjunto dorado (Fase 5.5.1)

> Objetivo: reunir 28 notas de voz reales con respuesta correcta conocida, para medir
> la precisión del bot antes de invitar pilotos. Detalles del plan en `golden_set.json`.

## Regla de oro

**NO enviar los audios al bot por WhatsApp.** Eso escribe transacciones falsas en el
Google Sheet real y contamina el libro contable. Grabar siempre fuera del flujo del bot.

## Cómo grabar (2 opciones)

- **Opción A:** usar la grabadora de voz del teléfono (app nativa). Un archivo por caso.
- **Opción B:** enviarse el audio a "Enviarme a mí mismo" en WhatsApp (Mensajes guardados).
  No toca el bot; luego se descarga del chat a la computadora.

## Pasar los audios a la computadora

Copiar los archivos aquí: `specs/golden_audio/` con nombre claro:
`caso_XX.descripcion_corta.ext` (ej. `caso_04.rojos_almuerzo.m4a`, `caso_12.ingreso_ventas.ogg`).

Al entregar cada audio, decirle al asesor:
1. qué dice la nota (la transcribe Whisper igual),
2. el **monto**, **categoría** y **tipo** (Gasto/Ingreso) correctos — la "verdad".

## Grilla de casos a grabar

| Nº | Tipo | Ejemplo de frase | Cantas grabar |
|---|---|---|---|
| 02–05 | Modismo "rojo" (₡1,000) | "Me gasté 5 rojos en el almuerzo" | 4 |
| 06–09 | Modismo "tucán" (₡5,000) | "Pagué 2 tucanes de inventario" | 3 (SPA: caso 1 ya cubre ingreso) |
| 10–12 | Modismo "teja" (₡100) | "Me cobraron 6 tejas por el motor" | 3 |
| 13–14 | Modismo "teja larga" (₡100,000) | "Compré el equipo, fueron una teja larga" | 2 |
| 15–18 | Números normales, gasto | "Compré mercadería por 25.000" | 4 |
| 19–21 | Números normales, ingreso | "Vendí y recibí 12.000" | 3 |
| 22–23 | Sin números ni modismos ⚠️ | "Pagué lo del transporte de la semana" | 2 |
| 24–25 | Monto en palabras | "Me gasté tres mil en el desayuno" | 2 |
| 26–27 | Audio largo, contexto extra | "Pagué al proveedor 15.000 y le eché combustible por 2 tucanes" | 2 |
| 28–29 | Ruido de fondo / acento fuerte | Grabar cerca de la caja o con la radio | 2 |

> Total: 29 (28 objetivo + 1 de margen). El caso #1 ("recibí 2 tucanes", 10/08/2026) ya está
> hecho y validado con E2E real.

## Lista de verificación al terminar

- [ ] Los 28–29 audios están en `specs/golden_audio/` con nombres `caso_XX...`.
- [ ] Para cada caso se definió el monto/categoría/tipo correcto.
- [ ] `golden_set.json` tiene cada caso con `transcripcion_esperada` y `esperado`.
- [ ] Ningún audio se envió al bot de prueba (no contaminar el Sheet real).