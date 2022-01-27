{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/release-21.11";
    flake-utils.url = "github:numtide/flake-utils";
  };
  outputs = { self, nixpkgs, flake-utils }:
    (flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = (import nixpkgs { inherit system; config = { }; });
      in
      rec {
        defaultPackage = pkgs.poetry2nix.mkPoetryApplication {
          projectDir = ./.;
        };
        defaultApp = {
          type = "app";
          program = "${defaultPackage}/bin/pystarport";
        };
        devShell = pkgs.poetry2nix.mkPoetryEnv {
          projectDir = ./.;
        };
      }
    ));
}
