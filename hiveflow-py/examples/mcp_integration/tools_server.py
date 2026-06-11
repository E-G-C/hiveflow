#!/usr/bin/env python3
"""MCP Tool Server -- provides research tools for live demos.

A small FastMCP server exposing 5 tools:
  - get_weather: Current weather for a city
  - calculate: Evaluate a math expression
  - lookup_capital: Capital city lookup
  - word_count: Count words in text
  - random_fact: Return a random fact about a topic

Designed to be spawned via stdio by the live MCP demo examples.

Usage (standalone, for testing):
    uv run python examples/mcp_integration/tools_server.py
"""

from mcp.server.fastmcp import FastMCP

server = FastMCP(
    name="research_tools",
    instructions="A collection of research and utility tools.",
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@server.tool()
def get_weather(city: str) -> str:
    """Get the current weather for a city.

    Args:
        city: Name of the city (e.g. 'London', 'Tokyo', 'New York')
    """
    # Simulated weather data for demo purposes
    weather_data = {
        "london": "London: 12C, cloudy with light rain, humidity 78%",
        "tokyo": "Tokyo: 22C, clear skies, humidity 45%",
        "new york": "New York: 18C, partly cloudy, humidity 62%",
        "paris": "Paris: 14C, overcast, humidity 71%",
        "sydney": "Sydney: 25C, sunny, humidity 55%",
        "berlin": "Berlin: 8C, fog, humidity 89%",
    }
    return weather_data.get(city.lower(), f"{city}: 20C, partly cloudy, humidity 60%")


@server.tool()
def calculate(expression: str) -> str:
    """Evaluate a mathematical expression safely.

    Args:
        expression: A math expression like '2 + 2' or '(15 * 3) / 5'
    """
    # Safe evaluation: only allow digits, operators, parens, spaces, decimal
    allowed = set("0123456789+-*/().% ")
    if not all(c in allowed for c in expression):
        return f"Error: expression contains invalid characters. Only math operators allowed."
    try:
        result = eval(expression)  # noqa: S307 -- restricted to safe chars
        return f"{expression} = {result}"
    except Exception as e:
        return f"Error evaluating '{expression}': {e}"


@server.tool()
def lookup_capital(country: str) -> str:
    """Look up the capital city of a country.

    Args:
        country: Name of the country (e.g. 'France', 'Japan')
    """
    capitals = {
        "france": "Paris",
        "japan": "Tokyo",
        "united states": "Washington, D.C.",
        "united kingdom": "London",
        "germany": "Berlin",
        "australia": "Canberra",
        "brazil": "Brasilia",
        "canada": "Ottawa",
        "india": "New Delhi",
        "china": "Beijing",
        "mexico": "Mexico City",
        "italy": "Rome",
        "spain": "Madrid",
        "south korea": "Seoul",
        "argentina": "Buenos Aires",
    }
    result = capitals.get(country.lower())
    if result:
        return f"The capital of {country} is {result}."
    return f"Capital not found for '{country}'. Try a well-known country name."


@server.tool()
def word_count(text: str) -> str:
    """Count the number of words in a text string.

    Args:
        text: The text to count words in
    """
    words = text.split()
    chars = len(text)
    return f"Word count: {len(words)} words, {chars} characters"


@server.tool()
def random_fact(topic: str) -> str:
    """Return an interesting fact about a topic.

    Args:
        topic: The topic to get a fact about (e.g. 'space', 'ocean', 'history')
    """
    facts = {
        "space": "The observable universe contains approximately 2 trillion galaxies.",
        "ocean": "The ocean covers 71% of Earth's surface and contains 97% of all water.",
        "history": "The Great Wall of China took over 2,000 years to build across multiple dynasties.",
        "math": "A googol is 10^100 -- a 1 followed by 100 zeros.",
        "animals": "Octopuses have three hearts and blue blood.",
        "technology": "The first computer bug was an actual bug -- a moth found in a Harvard Mark II in 1947.",
        "geography": "Russia spans 11 time zones, more than any other country.",
        "science": "Water can boil and freeze at the same time under specific conditions (triple point).",
    }
    return facts.get(topic.lower(), f"Interesting topic! Here's a general fact: honey never spoils.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    server.run(transport="stdio")
