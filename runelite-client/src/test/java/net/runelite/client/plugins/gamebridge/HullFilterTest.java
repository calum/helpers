/*
 * Copyright (c) 2026, Calum
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 * 1. Redistributions of source code must retain the above copyright notice, this
 *    list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright notice,
 *    this list of conditions and the following disclaimer in the documentation
 *    and/or other materials provided with the distribution.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
 * ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
 * WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
 * DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
 * ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
 * (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
 * LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
 * ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
 * SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */
package net.runelite.client.plugins.gamebridge;

import org.junit.Before;
import org.junit.Test;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class HullFilterTest
{
	private HullFilter filter;

	@Before
	public void setUp()
	{
		filter = new HullFilter();
	}

	// ---- default / empty state ----

	@Test
	public void defaultFilterIsEmpty()
	{
		assertTrue(filter.isEmpty());
	}

	@Test
	public void defaultFilterMatchesAnyId()
	{
		assertTrue(filter.matches(1234, "Goblin"));
	}

	@Test
	public void defaultFilterMatchesNullName()
	{
		assertTrue(filter.matches(999, null));
	}

	// ---- parse: empty / null / whitespace ----

	@Test
	public void emptyStringIsEmpty()
	{
		filter.parse("");
		assertTrue(filter.isEmpty());
	}

	@Test
	public void nullIsEmpty()
	{
		filter.parse(null);
		assertTrue(filter.isEmpty());
	}

	@Test
	public void whitespaceOnlyIsEmpty()
	{
		filter.parse("   ");
		assertTrue(filter.isEmpty());
	}

	@Test
	public void emptyFilterAfterParseMatchesEverything()
	{
		filter.parse("");
		assertTrue(filter.matches(9999, "anything"));
		assertTrue(filter.matches(0, null));
	}

	// ---- ID matching ----

	@Test
	public void matchesSingleId()
	{
		filter.parse("42");
		assertTrue(filter.matches(42, null));
	}

	@Test
	public void doesNotMatchDifferentId()
	{
		filter.parse("42");
		assertFalse(filter.matches(43, null));
	}

	@Test
	public void matchesMultipleIds()
	{
		filter.parse("1276,3106");
		assertTrue(filter.matches(1276, "Oak tree"));
		assertTrue(filter.matches(3106, "Goblin"));
	}

	@Test
	public void idMatchIgnoresName()
	{
		filter.parse("1276");
		assertTrue(filter.matches(1276, "anything"));
		assertTrue(filter.matches(1276, null));
	}

	// ---- Name matching ----

	@Test
	public void matchesByNameExact()
	{
		filter.parse("Goblin");
		assertTrue(filter.matches(999, "Goblin"));
	}

	@Test
	public void matchesByNameCaseInsensitiveEntityName()
	{
		filter.parse("Goblin");
		assertTrue(filter.matches(999, "goblin"));
		assertTrue(filter.matches(999, "GOBLIN"));
		assertTrue(filter.matches(999, "gObLiN"));
	}

	@Test
	public void matchesByNameCaseInsensitiveFilterToken()
	{
		filter.parse("GOBLIN");
		assertTrue(filter.matches(999, "goblin"));
		assertTrue(filter.matches(999, "Goblin"));
	}

	@Test
	public void doesNotMatchUnknownName()
	{
		filter.parse("Goblin");
		assertFalse(filter.matches(999, "Cow"));
	}

	@Test
	public void nullNameDoesNotMatchNameEntry()
	{
		filter.parse("Goblin");
		assertFalse(filter.matches(999, null));
	}

	// ---- Mixed IDs and names ----

	@Test
	public void mixedIdsAndNames()
	{
		filter.parse("1276,Goblin,3106");
		assertTrue(filter.matches(1276, "Oak tree"));  // matched by ID
		assertTrue(filter.matches(999, "Goblin"));     // matched by name
		assertTrue(filter.matches(3106, "Cow"));       // matched by ID
		assertFalse(filter.matches(999, "Cow"));       // neither ID nor name
		assertFalse(filter.matches(9999, "something"));
	}

	@Test
	public void isNotEmptyAfterParsingEntries()
	{
		filter.parse("Goblin");
		assertFalse(filter.isEmpty());

		filter.parse("1276");
		assertFalse(filter.isEmpty());
	}

	// ---- Whitespace handling ----

	@Test
	public void stripsLeadingAndTrailingWhitespaceFromTokens()
	{
		filter.parse(" 1276 , Oak tree , Goblin ");
		assertTrue(filter.matches(1276, "X"));
		assertTrue(filter.matches(999, "Oak tree"));
		assertTrue(filter.matches(999, "Goblin"));
	}

	// ---- Empty / degenerate tokens ----

	@Test
	public void commasOnlyTreatedAsEmpty()
	{
		filter.parse(",,,");
		assertTrue(filter.isEmpty());
		assertTrue(filter.matches(9999, "whatever"));
	}

	@Test
	public void skipsEmptyTokensInMixedList()
	{
		filter.parse("1276,,Goblin,");
		assertTrue(filter.matches(1276, "X"));
		assertTrue(filter.matches(999, "Goblin"));
	}

	// ---- Reset / replace ----

	@Test
	public void parseEmptyResetsToMatchAll()
	{
		filter.parse("1276,Goblin");
		assertFalse(filter.isEmpty());

		filter.parse("");
		assertTrue(filter.isEmpty());
		assertTrue(filter.matches(9999, "unknown"));  // empty = all match
	}

	@Test
	public void parseReplacesExistingEntries()
	{
		filter.parse("Goblin");
		filter.parse("Cow");
		assertFalse(filter.matches(999, "Goblin"));  // old entry removed
		assertTrue(filter.matches(999, "Cow"));      // new entry active
	}

	@Test
	public void parseNullAfterPopulatedResetsToMatchAll()
	{
		filter.parse("1276");
		filter.parse(null);
		assertTrue(filter.isEmpty());
		assertTrue(filter.matches(1276, "anything"));
	}

	// ---- Edge cases ----

	@Test
	public void multiWordNamesMatchedExactly()
	{
		filter.parse("Iron rocks");
		assertTrue(filter.matches(9999, "Iron rocks"));
		assertFalse(filter.matches(9999, "Iron"));
		assertFalse(filter.matches(9999, "rocks"));
	}

	@Test
	public void largeIdParsedCorrectly()
	{
		filter.parse("2147483647");  // Integer.MAX_VALUE
		assertTrue(filter.matches(Integer.MAX_VALUE, null));
	}

	@Test
	public void zeroIdParsedCorrectly()
	{
		filter.parse("0");
		assertTrue(filter.matches(0, null));
		assertFalse(filter.matches(1, null));
	}
}
