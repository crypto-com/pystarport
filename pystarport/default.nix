{ pkgs ? import <nixpkgs> {}, commit ? "" }:
with pkgs;
pkgs.mkShell {
  buildInputs = [
    python38
    python38Packages.grpcio
    python38Packages.grpcio-tools
    git
  ];
}
