#### LTTng
- LTTng is a tool that records events from the Linux kernel and from userspace.
- It has less overhead.
- Saves traces in compact file format.

#### Key Terms
- Session: One recording job.
- Domain: Where are the events coming from? The kernel domain is the OS. The Useerspace domain is the application.
- Event: One thing that happened, like a CPU switch.
- Channel: A buffer that holds events before they are written to disk.
- Tracepoint: A marked spot in code that can send an event.
- Consumer Daemon: A background program that moves events from the buffers to files.
- CTF: Common Trace Format.


#### How it works
`Tracepoints sends events → Buffer → Consumer Daemon → File`


#### How to install
`sudo apt-get install lttng-tools lttng-modules-dkms babeltrace2`

- `lttng-tools` gives you the `lttng` command.
- `lttng-modules-dkms` lets LTTng trace the kernel.
- `babeltrace2` reads the trace files.


#### How to record a session
1. *Create a session: (trace gets saved under ~/lttng-traces/my-session-<date>)*
    - lttng create <session-name>
   
2. *Choose which events to trace:*
    - lttng enable-event -kernel <kernel-domain> <event-name>
    - example 1: lttng enable-event --kernel --syscall --all ( enables every system call available in the Linux kernel)
    - example 2: lttng enable-event --kernel sched_switch (enables a single specific kernel tracepoint (sched_switch) that records CPU context switches between processes or threads.)
   
3. *Start recording:*
    - lttng start

4. *Do something*

5. *Stop recording:*
    - lttng stop

6. *Clean up the session: (removes the session from LTTng. It does not delete the files.*
    - lttng destroy


#### How to read a trace
`babeltrace2 ~/lttng-traces/my-session-*`

Output looks like this:
`[11:18:48.397977054] (+0.000000544) stratatrace-ss.us-east1-d.c.teleeporter.internal syscall_entry_read: { cpu_id = 1 }, { pid = 2292495, tid = 2292495, procname = "sed", cgroup_ns = 4026531835, pid_ns = 4026531836, net_ns = 4026531833, ipc_ns = 4026531839, user_ns = 4026531837 }, { fd = 3, count = 832 }`


###### Timestamp
- `[11:18:48.397977054]`: Time of the event.
- `(+0.000000544)`: Time since the last event.

###### Host
- `stratatrace-ss.us-east1-d.c.teleeporter.internal`: is the machine name. (collected on a Google Cloud VM)

###### Event Name
- `syscall_entry_read`: Name of the event.

###### CPU
- `{ cpu_id = 1 }`: Which CPU core ran it.

###### Process Context
- `pid = 2292495`: The process ID.
- `tid = 2292495`: The thread ID. It is the same as the process ID. So it is the main thread.
- `procname = "sed"`: Program name.
- `*_ns`: fields are the namespace IDs.

###### Inputs of the call
- `fd = 3`: File descriptor. Number the process uses for an open file.
- `count = 832`: is the most bytes the process asked for.


#### FYI

**What is a file descriptor?**

- Every process starts with three: 0 is input, 1 is output, 2 is errors.
- The next file the process opens gets number 3.
- So `fd = 3` is the first file `sed` opened. You can find which file by looking for the earlier `openat` event that returned 3.

**What are namespaces?**

- A namespace is a way Linux separates processes. Containers use them.
- Each type has an ID number: cgroup, pid, net, ipc, and user.
- These numbers (4026531835 and similar) are the default ones for the whole machine.
- This means `sed` is not inside a container. It runs on the host.
- If the numbers were different, the process would be in a container.

**What is `count = 832`?**

- It is the size the process asked for. It is not the size it got.
- The real number of bytes comes in the exit event, as `ret`.
- 832 bytes is a very common size at program start. The system loader reads the first 832 bytes of each shared library. This is likely `sed` starting up and loading a library.