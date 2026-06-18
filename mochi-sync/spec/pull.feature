Feature: Pull cards from Mochi
  As a user who edited cards in Mochi
  I want to pull a deck back into local markdown
  So that the vault reflects Mochi-side changes

  Background:
    Given a valid MOCHI_API_KEY is available
    And the vault root is configured

  Scenario: Pull a deck into an output folder
    When the "pull" command is run with a --deck-id and --out folder
    Then each non-trashed card is written as a markdown file in the output folder
    And every file gets a "mochi-id" frontmatter and a "mochi" tag
    And a pulled-card count is printed

  Scenario: Derive a filename from the card
    Given a card with a name
    When it is pulled
    Then the file is named after the card name with filesystem-unsafe characters removed
    And a card without a name falls back to its first content line, else its id

  Scenario: Lift the leading metadata block into frontmatter
    Given a card body that begins with a "key: value" block and a "---" separator
    When it is pulled
    Then the managed keys are extracted into frontmatter properties
    And the separator is removed from the body

  Scenario: Rewrite image references to Obsidian embeds
    Given a card referencing images (bare or "@media/" prefixed)
    When it is pulled
    Then each reference becomes an "![[filename]]" embed

  Scenario: Report attachments whose binaries are not in the vault
    Given a card with an attachment whose file is not present in the configured vault
    When the deck is pulled
    Then the embed is still written
    And the missing attachment is reported, noting the API cannot download binaries

  Scenario: Preview without writing
    When a pull is run with --dry-run
    Then the files that would be written are listed
    And nothing is written to disk
