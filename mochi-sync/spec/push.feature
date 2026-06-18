Feature: Push notes to Mochi
  As a user editing cards in Obsidian
  I want to push notes to Mochi
  So that my vault is the source of truth

  Background:
    Given a valid MOCHI_API_KEY is available
    And the vault root is configured

  Scenario: Create a new card from a note without a mochi-id
    Given a note with no "mochi-id" frontmatter
    When the note is pushed to a deck
    Then a new card is created in that deck
    And the new card id is written back into the note's "mochi-id" frontmatter

  Scenario: Update an existing card idempotently
    Given a note whose frontmatter already has a "mochi-id"
    When the note is pushed
    Then the existing card is updated
    And no duplicate card is created

  Scenario: Resolve a deck by its full path
    When a note is pushed with --deck-path "A/B/C"
    Then the deck is resolved against the live deck tree
    And the push fails if that path does not exist and --create-decks was not given

  Scenario: Create missing deck levels on request
    When a note is pushed with --deck-path "A/B/C" and --create-decks
    Then any missing deck levels are created before the card is pushed

  Scenario: Push a whole folder of notes
    Given a folder containing multiple ".md" notes
    When the folder is pushed
    Then every ".md" file not starting with "_" is pushed as a card

  Scenario: Upload referenced images
    Given a note that embeds "![[diagram.png]]" or "![](path/diagram.png)"
    When the note is pushed
    Then the image file is located near the note or anywhere in the configured vault
    And it is uploaded as a card attachment
    And the card content references the bare filename "![](diagram.png)"

  Scenario: Leave unresolved images untouched
    Given a note referencing an image that cannot be found
    When the note is pushed
    Then the reference is left as-is and a warning is printed

  Scenario: Preview without writing
    When a push is run with --dry-run
    Then the intended create/update actions are printed
    And no write API calls are made
