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

import java.io.IOException;
import java.io.PrintWriter;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.concurrent.CopyOnWriteArrayList;
import lombok.extern.slf4j.Slf4j;

/**
 * Embedded TCP server that accepts connections on localhost and broadcasts
 * newline-delimited JSON messages to every connected client.
 * Disconnected clients are pruned lazily on the next broadcast.
 */
@Slf4j
class BridgeServer
{
	private static final class ClientEntry
	{
		final Socket socket;
		final PrintWriter writer;

		ClientEntry(Socket socket) throws IOException
		{
			this.socket = socket;
			this.writer = new PrintWriter(socket.getOutputStream(), true);
		}
	}

	private ServerSocket serverSocket;
	private Thread acceptThread;
	private final CopyOnWriteArrayList<ClientEntry> clients = new CopyOnWriteArrayList<>();

	void start(int port) throws IOException
	{
		serverSocket = new ServerSocket(port, 10, InetAddress.getByName("127.0.0.1"));
		log.info("Game Bridge listening on 127.0.0.1:{}", port);
		acceptThread = new Thread(this::acceptLoop, "game-bridge-accept");
		acceptThread.setDaemon(true);
		acceptThread.start();
	}

	void stop()
	{
		try
		{
			if (serverSocket != null)
			{
				serverSocket.close();
			}
		}
		catch (IOException e)
		{
			log.warn("Game Bridge: error closing server socket", e);
		}
		for (ClientEntry entry : clients)
		{
			try
			{
				entry.socket.close();
			}
			catch (IOException ignored)
			{
			}
		}
		clients.clear();
	}

	/**
	 * Writes {@code line} followed by a newline to every connected client.
	 * Clients that have disconnected are removed from the list.
	 * Must be called from a single thread (the client thread).
	 */
	void broadcast(String line)
	{
		for (ClientEntry entry : clients)
		{
			entry.writer.println(line);
			if (entry.writer.checkError())
			{
				log.debug("Game Bridge: client disconnected, removing");
				clients.remove(entry);
				try
				{
					entry.socket.close();
				}
				catch (IOException ignored)
				{
				}
			}
		}
	}

	private void acceptLoop()
	{
		while (!serverSocket.isClosed())
		{
			try
			{
				Socket socket = serverSocket.accept();
				socket.setTcpNoDelay(true);
				clients.add(new ClientEntry(socket));
				log.info("Game Bridge: client connected from {}", socket.getInetAddress());
			}
			catch (IOException e)
			{
				if (!serverSocket.isClosed())
				{
					log.warn("Game Bridge: accept error", e);
				}
			}
		}
	}
}
