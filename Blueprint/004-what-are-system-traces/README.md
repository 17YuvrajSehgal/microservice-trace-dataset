#### What are system traces?
System tracing records what the operating system (OS) does while your program runs. It shows events like file reads, network calls, and process switches.

It helps us to understand what the machine is doing underneath our code. And kernel trace records these events, in time order.


Run this in a Linux terminal:

```
strace -tt -T cat hello.txt
```

- `-tt` adds the time of each call.
- `-T` adds how long each call took.

The output looks like this:

```
10:32:00.100001 openat(AT_FDCWD, "hello.txt", O_RDONLY) = 3 <0.000030>
10:32:00.100100 read(3, "Hello world\n", 131072) = 12 <0.000012>
10:32:00.100200 write(1, "Hello world\n", 12) = 12 <0.000015>
10:32:00.100300 close(3) = 0 <0.000008>
```

**How to read one line**

Take the first line:

- `10:32:00.100001`: The time of the call.
- `openat(...)`: The syscall name and its inputs. Here it opens `hello.txt` for reading.
- `= 3`: The result. Here it is a file handle number.
- `<0.000030>`: How long it took. Here it is 30 microseconds.

