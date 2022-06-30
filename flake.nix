{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/22.05";
    flake-utils.url = "github:numtide/flake-utils";
    poetry2nix = {
      url = "github:nix-community/poetry2nix";
      inputs.flake-utils.follows = "flake-utils";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };
  outputs = { self, nixpkgs, flake-utils, poetry2nix }:
    (flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = (import nixpkgs {
          inherit system; config = { };
          overlays = [
            poetry2nix.overlay
          ];
        });
      in
      rec {
        packages.default = pkgs.poetry2nix.mkPoetryApplication
          {
            projectDir = ./.;
            overrides = pkgs.poetry2nix.overrides.withDefaults
              (self: super: {
                pyparsing = super.pyparsing.overridePythonAttrs (
                  old: {
                    nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [ self.flit-core ];
                  }
                );
                jsonschema = super.jsonschema.overridePythonAttrs (
                  old: {
                    nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [ self.hatchling self.hatch-vcs ];
                  }
                );
              });
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
