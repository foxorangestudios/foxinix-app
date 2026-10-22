# Foxinix para Arch Linux

Paquete binario `foxinix-bin` a partir del AppImage oficial de Foxinix.
Instala la aplicación completa en `/opt/foxinix` y deja el comando
`foxinix`, el lanzador de escritorio y los iconos en el sistema.

## Compilar e instalar

```bash
cd desktop/arch/foxinix-bin
makepkg -si
```

O instalar un paquete ya compilado:

```bash
sudo pacman -U foxinix-bin-0.1.5-1-x86_64.pkg.tar.zst
```

## AUR

El `PKGBUILD` y `.SRCINFO` están listos para publicarse como `foxinix-bin`.
La publicación en AUR requiere una cuenta y una clave SSH registrada en
`aur.archlinux.org`; no se hace automáticamente desde este repositorio.

Para publicarlo:

```bash
git clone ssh://aur@aur.archlinux.org/foxinix-bin.git
cp PKGBUILD .SRCINFO foxinix-bin/
cd foxinix-bin
git add PKGBUILD .SRCINFO
git commit -m "foxinix-bin 0.1.5-1"
git push
```
