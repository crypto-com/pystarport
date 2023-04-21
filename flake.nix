{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/release-22.11";
    flake-utils.url = "github:numtide/flake-utils";
  };
  outputs = { self, nixpkgs, flake-utils }:
    (flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = (import nixpkgs { inherit system; config = { }; });
        overrides = pkgs.poetry2nix.overrides.withDefaults (pkgs.lib.composeManyExtensions [
          (self: super:
            let
              buildSystems = {
                eth-bloom = [ "setuptools" ];
                cprotobuf = [ "setuptools" ];
                durations = [ "setuptools" ];
                multitail2 = [ "setuptools" ];
                pytest-github-actions-annotate-failures = [ "setuptools" ];
                flake8-black = [ "setuptools" ];
                multiaddr = [ "setuptools" ];
              };
            in
            pkgs.lib.mapAttrs
              (attr: systems: super.${attr}.overridePythonAttrs
                (old: {
                  nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ map (a: self.${a}) systems;
                }))
              buildSystems
          )
          (self: super: {
            eth-bloom = super.eth-bloom.overridePythonAttrs {
              preConfigure = ''
                substituteInPlace setup.py --replace \'setuptools-markdown\' ""
              '';
            };
            pyyaml-include = super.pyyaml-include.overridePythonAttrs {
              preConfigure = ''
                substituteInPlace setup.py --replace "setup()" "setup(version=\"1.3\")"
              '';
            };
          })
        ]);
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
