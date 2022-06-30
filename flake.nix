{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/22.05";
    flake-utils.url = "github:numtide/flake-utils";
  };
  outputs = { self, nixpkgs, flake-utils }:
    (flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = (import nixpkgs { inherit system; config = { }; });
      in
      rec {
        packages.default = pkgs.poetry2nix.mkPoetryApplication {
          projectDir = ./.;
        };
        apps.default = {
          type = "app";
          program = "${packages.default}/bin/pystarport";
        };
        devShell = pkgs.poetry2nix.mkPoetryEnv {
          projectDir = ./.;
        };
      }
    ));
}
