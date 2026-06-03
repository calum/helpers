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

import java.util.Collections;
import java.util.HashSet;
import java.util.Set;

/**
 * Determines which entities have their convex hull included in bridge messages.
 * Each CSV token is tried as an integer ID first; anything that does not parse
 * as an integer is treated as a case-insensitive name.
 * An empty filter matches everything (all entities get hulls).
 */
class HullFilter
{
	private Set<Integer> ids = Collections.emptySet();
	private Set<String> names = Collections.emptySet();
	private boolean empty = true;

	void parse(String csv)
	{
		if (csv == null || csv.trim().isEmpty())
		{
			ids = Collections.emptySet();
			names = Collections.emptySet();
			empty = true;
			return;
		}

		Set<Integer> newIds = new HashSet<>();
		Set<String> newNames = new HashSet<>();
		for (String token : csv.split(","))
		{
			String t = token.trim();
			if (t.isEmpty())
			{
				continue;
			}
			try
			{
				newIds.add(Integer.parseInt(t));
			}
			catch (NumberFormatException ex)
			{
				newNames.add(t.toLowerCase());
			}
		}
		ids = newIds;
		names = newNames;
		empty = newIds.isEmpty() && newNames.isEmpty();
	}

	/**
	 * Returns true if this entity should have its hull included.
	 * When the filter is empty every entity matches.
	 */
	boolean matches(int id, String name)
	{
		if (empty)
		{
			return true;
		}
		if (ids.contains(id))
		{
			return true;
		}
		return name != null && names.contains(name.toLowerCase());
	}
}
