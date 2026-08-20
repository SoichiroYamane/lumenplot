{
  description = "Reproducible NixOS development environment for lumenplot";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/f2b17eb1b90f6a359082035b4538d4c63017aec3";

  outputs =
    { nixpkgs, ... }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      devShells = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          default = pkgs.mkShellNoCC {
            packages = [
              pkgs.cargo
              pkgs.clippy
              pkgs.rustc
              pkgs.rustfmt
            ];
            RUST_BACKTRACE = "1";
          };
        }
      );
    };
}
