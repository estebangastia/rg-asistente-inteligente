"""
backup.py — Respaldo manual y prueba de restauración
RG S.A. — Sistema de Asistencia Inteligente

    python backup.py              → genera una copia de seguridad ahora
    python backup.py --verificar  → restaura la última copia en una base
                                    temporal y compara contra producción
    python backup.py --listar     → lista las copias disponibles

La copia diaria automática la ejecuta el scheduler a las 00:00.
"""
import json
import sys
from app.respaldo import crear_backup, verificar_restauracion, listar_backups, ErrorRespaldo


def main():
    try:
        if "--listar" in sys.argv:
            copias = listar_backups()
            if not copias:
                print("No hay copias de seguridad.")
            for c in copias:
                print(f"  {c['fecha']}  {c['tamano_kb']:>8} KB  {c['archivo']}")
        elif "--verificar" in sys.argv:
            print("Restaurando la última copia en una base temporal aislada...")
            r = verificar_restauracion()
            print(f"\nCopia verificada: {r['archivo']}")
            print(f"{'Tabla':<16}{'Producción':>12}{'Backup':>10}")
            for tabla, v in r["tablas"].items():
                print(f"{tabla:<16}{v['produccion']:>12}{v['backup']:>10}")
            print(f"\nResultado: {r['resultado']}")
        else:
            info = crear_backup()
            print(json.dumps(info, indent=2, ensure_ascii=False))
            print("Copia de seguridad generada correctamente.")
    except ErrorRespaldo as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
