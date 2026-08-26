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
          # libiconv is a macOS SDK tbd stub; when the linker is not driven
          # through Apple's clang with SDK search paths, `-liconv` fails.
          # Providing the nixpkgs libiconv on darwin keeps `pip install -e .`
          # (maturin/rust link of lumenplot_mpl._native) working outside Xcode
          # toolchains. No effect on Linux systems.
          darwinOnly =
            if pkgs.stdenv.hostPlatform.isDarwin then [ pkgs.libiconv ] else [ ];
        in
        {
          default = pkgs.mkShellNoCC {
            packages = [
              pkgs.cargo
              pkgs.clippy
              pkgs.python3
              pkgs.rustc
              pkgs.rustfmt
            ] ++ darwinOnly;
            RUST_BACKTRACE = "1";
          };
        }
      );
    };
}
