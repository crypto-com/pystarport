# Project Setup

1. Copy `.envrc.example` to `.envrc`.
2. Install [nix](https://nixos.org/download/).
3. Install [direnv](https://direnv.net/) and [nix-direnv](https://github.com/nix-community/nix-direnv).
4. Run `direnv allow` at project root. This is to automatically load the environment when you `cd` into the project directory in the terminal in the future.
5. Run `which python` to verify that the Python interpreter is from the nix environment.

    ```shell
    $ which python
    /nix/store/9l232zbyi3nisqn9s3li4imyv37753vc-python3-3.11.9-env/bin/python
    ```

    Path should look similar to the above from `/nix/store`. This confirms that you are using the correct Python interpreter.

6. Run `python -mpytest` to execute all tests.

If you are able to run all tests, you are ready to go!

## VS Code

1. For intellisense in VS Code, add result of `which python` to your `.vscode/settings.json`:

    ```json
    {
        "python.defaultInterpreterPath": "output of `which python`"
    }
    ```
