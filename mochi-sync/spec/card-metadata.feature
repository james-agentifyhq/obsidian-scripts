Feature: Card metadata round-trip
  As a user of loci / memory-palace cards
  I want metadata kept as Obsidian properties but rendered inside the Mochi card
  So that notes stay clean while cards still show their metadata

  The managed keys are: location, floor, room, loci, System.

  Scenario: Push injects frontmatter metadata into the card body
    Given a note with managed metadata in its frontmatter
    When the note is pushed
    Then the metadata is rendered as a leading "key: value" block in the card content
    And the block is followed by a "---" separator before the body

  Scenario: Empty metadata fields are omitted
    Given a note where some managed keys are empty
    When the note is pushed
    Then only the non-empty managed keys appear in the card body block

  Scenario: Pull extracts the metadata block back into frontmatter
    Given a pulled card whose body starts with a managed "key: value" block
    When it is pulled
    Then those keys become frontmatter properties
    And numeric values are written unquoted while text values are quoted

  Scenario: Non-managed key/value lines are left in the body
    Given a card body with a "note:" line after the separator
    When it is pulled
    Then that line is preserved in the body and not lifted into frontmatter
