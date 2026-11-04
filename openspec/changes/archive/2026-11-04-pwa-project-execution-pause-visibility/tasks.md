## 1. Proyectar y mostrar la pausa de ejecución

- [x] 1.1 Añadir `effective_pause` y `global_pause` opcionales al tipo frontend existente de `execution_policy` y mostrar un indicador de pausa por proyecto independiente de su estado administrativo.
- [x] 1.2 Mostrar el indicador de pausa global a partir de los `execution_policy` de los proyectos recibidos, manteniendo el refresh existente como fuente de actualización.

## 2. Verificar el comportamiento

- [x] 2.1 Añadir pruebas frontend focalizadas para flags activos/inactivos, independencia del estado administrativo, pausa global y actualización tras refresh.
- [x] 2.2 Ejecutar la suite frontend (`npm --prefix frontend test`) y el build de producción (`npm --prefix frontend run build`); ambos deben finalizar correctamente.
