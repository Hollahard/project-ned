use crate::HttpError;
use hermes_resource_host::WorkerGroup;
use std::net::{Ipv4Addr, SocketAddr, SocketAddrV4, TcpStream};
use windows_sys::Win32::Foundation::ERROR_INSUFFICIENT_BUFFER;
use windows_sys::Win32::NetworkManagement::IpHelper::{
    GetExtendedTcpTable, TCP_TABLE_OWNER_PID_ALL,
};
use windows_sys::Win32::Networking::WinSock::AF_INET;

pub(crate) fn verify(stream: &TcpStream, group: &WorkerGroup) -> Result<u32, HttpError> {
    let local = ipv4(
        stream
            .local_addr()
            .map_err(|_| HttpError("HTTP_SOCKET_QUERY"))?,
    )?;
    let peer = ipv4(
        stream
            .peer_addr()
            .map_err(|_| HttpError("HTTP_SOCKET_QUERY"))?,
    )?;
    if *local.ip() != Ipv4Addr::LOCALHOST || *peer.ip() != Ipv4Addr::LOCALHOST {
        return Err(HttpError("HTTP_OWNER_DENIED"));
    }
    let pid = established_owner(peer, local)?;
    if !group
        .contains_observed_pid(pid)
        .map_err(|_| HttpError("HTTP_OWNER_QUERY"))?
    {
        return Err(HttpError("HTTP_OWNER_DENIED"));
    }
    Ok(pid)
}

fn ipv4(address: SocketAddr) -> Result<SocketAddrV4, HttpError> {
    match address {
        SocketAddr::V4(a) => Ok(a),
        _ => Err(HttpError("HTTP_OWNER_DENIED")),
    }
}

fn established_owner(server: SocketAddrV4, client: SocketAddrV4) -> Result<u32, HttpError> {
    let mut bytes = 0u32;
    // SAFETY: documented sizing query; all pointers valid for the call.
    let first = unsafe {
        GetExtendedTcpTable(
            std::ptr::null_mut(),
            &mut bytes,
            0,
            AF_INET as u32,
            TCP_TABLE_OWNER_PID_ALL,
            0,
        )
    };
    if first != 0 && first != ERROR_INSUFFICIENT_BUFFER {
        return Err(HttpError("HTTP_OWNER_QUERY"));
    }
    for _ in 0..3 {
        if !(4..=4 * 1024 * 1024).contains(&bytes) {
            return Err(HttpError("HTTP_OWNER_TABLE_LIMIT"));
        }
        let allocated = bytes as usize;
        // DWORD alignment for the native table; round allocation up while
        // passing its original bounded size. No unaligned Rust struct casts.
        let mut table = vec![0u32; allocated.div_ceil(4)];
        let result = unsafe {
            GetExtendedTcpTable(
                table.as_mut_ptr().cast(),
                &mut bytes,
                0,
                AF_INET as u32,
                TCP_TABLE_OWNER_PID_ALL,
                0,
            )
        };
        if result == ERROR_INSUFFICIENT_BUFFER {
            continue;
        }
        if result != 0 || bytes as usize > allocated || bytes < 4 {
            return Err(HttpError("HTTP_OWNER_QUERY"));
        }
        return match_table(&table, bytes as usize, server, client);
    }
    Err(HttpError("HTTP_OWNER_TABLE_CHANGED"))
}

fn match_table(
    table: &[u32],
    bytes: usize,
    server: SocketAddrV4,
    client: SocketAddrV4,
) -> Result<u32, HttpError> {
    let count = table[0] as usize;
    if count > (bytes - 4) / 24 || 1 + count * 6 > table.len() {
        return Err(HttpError("HTTP_OWNER_QUERY"));
    }
    let mut owner = None;
    for row in table[1..1 + count * 6].chunks_exact(6) {
        let endpoint = SocketAddrV4::new(
            Ipv4Addr::from(row[1].to_ne_bytes()),
            u16::from_be(row[2] as u16),
        );
        let other = SocketAddrV4::new(
            Ipv4Addr::from(row[3].to_ne_bytes()),
            u16::from_be(row[4] as u16),
        );
        // MIB_TCP_STATE_ESTAB=5. Reverse BOTH addresses and ports from the
        // connected client socket; neither LISTEN nor port-only matches count.
        if row[0] == 5
            && endpoint == server
            && other == client
            && (row[5] == 0 || owner.replace(row[5]).is_some())
        {
            return Err(HttpError("HTTP_OWNER_AMBIGUOUS"));
        }
    }
    owner.ok_or(HttpError("HTTP_OWNER_NOT_OBSERVED"))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn exact_reversed_tuple_established_only_and_unique() {
        let server = SocketAddrV4::new(Ipv4Addr::LOCALHOST, 8000);
        let client = SocketAddrV4::new(Ipv4Addr::LOCALHOST, 49152);
        let address = u32::from_ne_bytes(Ipv4Addr::LOCALHOST.octets());
        let row = [
            5,
            address,
            server.port().to_be() as u32,
            address,
            client.port().to_be() as u32,
            123,
        ];
        let mut table = vec![1];
        table.extend(row);
        assert_eq!(match_table(&table, 28, server, client).unwrap(), 123);
        table[1] = 2;
        assert!(match_table(&table, 28, server, client).is_err());
        table[1] = 5;
        assert!(match_table(&table, 28, client, server).is_err());
        table[0] = 2;
        table.extend(row);
        assert!(match_table(&table, 52, server, client).is_err());
        assert!(match_table(&table, 28, server, client).is_err());
    }
}
