{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    poetry2nix = {
      url = "github:nix-community/poetry2nix";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.flake-utils.follows = "flake-utils";
    };
  };
  outputs = { self, nixpkgs, flake-utils, poetry2nix }:
    (flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = (import nixpkgs {
          inherit system;
          config = { };
          overlays = [
            poetry2nix.overlays.default
          ];
        });
        overrides = pkgs.poetry2nix.overrides.withDefaults (self: super:
          let
            buildSystems = {
              durations = [ "setuptools" ];
              multitail2 = [ "setuptools" ];
              pytest-github-actions-annotate-failures = [ "setuptools" ];
            };
          in
          pkgs.lib.mapAttrs
            (attr: systems: super.${attr}.overridePythonAttrs
              (old: {
                nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ map (a: self.${a}) systems;
              }))
            buildSystems
        );
      in
      rec {
        packages.default = pkgs.poetry2nix.mkPoetryApplication
          {
            projectDir = ./.;
            inherit overrides;
          };
        apps.default = {
          type = "app";
          program = "${packages.default}/bin/pystarport";
        };
        devShell = pkgs.poetry2nix.mkPoetryEnv {
          projectDir = ./.;
          inherit overrides;
        };
      }
    ));
}
