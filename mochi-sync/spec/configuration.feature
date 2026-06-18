Feature: Vault root configuration
  As a user running the CLI from outside the vault
  I want the vault location to be configurable
  So that the script keeps working no matter where it is installed

  The vault root is needed to resolve image embeds by basename (push) and to
  detect missing attachments (pull).

  Scenario: Resolve the vault root from config.json
    Given a config.json next to the script containing a "vault_root"
    And neither --vault-root nor MOCHI_VAULT_ROOT is set
    When a command needs the vault root
    Then the path from config.json is used (with "~" expanded)

  Scenario: Environment variable overrides config.json
    Given config.json sets a "vault_root"
    And MOCHI_VAULT_ROOT is set to a different existing directory
    When a command needs the vault root
    Then the MOCHI_VAULT_ROOT path is used

  Scenario: The --vault-root flag overrides everything
    Given config.json and MOCHI_VAULT_ROOT both point elsewhere
    When the command is run with "--vault-root /path/to/vault"
    Then the flag path is used

  Scenario: Missing configuration fails with guidance
    Given no --vault-root, no MOCHI_VAULT_ROOT, and no vault_root in config.json
    When a command that needs the vault root is run
    Then the CLI exits with instructions for all three ways to set it

  Scenario: A configured but nonexistent vault root is rejected
    Given a configured vault root that does not point to a directory
    When a command that needs the vault root is run
    Then the CLI exits reporting the missing path

  Scenario: The decks command does not require a vault root
    Given no vault root is configured
    When the "decks" command is run
    Then it succeeds because it only talks to the API
