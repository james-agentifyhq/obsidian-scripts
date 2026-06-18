Feature: List decks
  As a user
  I want to list my Mochi deck tree with ids
  So that I can verify connectivity and find deck paths to push to

  Background:
    Given a valid MOCHI_API_KEY is available

  Scenario: List the full deck tree
    When the "decks" command is run
    Then every deck is printed as an indented path
    And each deck shows its id
    And a total deck count is printed

  Scenario: Decks act as a connectivity check
    Given the API key is missing or invalid
    When the "decks" command is run
    Then the CLI exits with an authentication-related error
