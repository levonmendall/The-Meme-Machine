.text
.global _start
_start:
    mov %rsp,%r12
    sub $176,%rsp
    mov %rsp,%r14
    lea 16(%rsp),%r15
    mov $5,%eax
    mov $5,%edi
    mov %r15,%rsi
    syscall
    test %rax,%rax
    js failed
    mov 24(%r15),%eax
    and $0170000,%eax
    cmp $0010000,%eax
    jne failed
    mov $72,%eax
    mov $5,%edi
    mov $3,%esi
    xor %edx,%edx
    syscall
    test %rax,%rax
    js failed
    and $3,%eax
    jne failed
    movl $5,(%r14)
    movw $25,4(%r14)
    call check_lifeline
    mov $110,%eax
    syscall
    mov %rax,%r13
    mov $157,%eax
    mov $1,%edi
    mov $9,%esi
    xor %edx,%edx
    xor %r10d,%r10d
    xor %r8d,%r8d
    syscall
    test %rax,%rax
    js failed
    mov $110,%eax
    syscall
    cmp %r13,%rax
    jne failed
    call check_lifeline
    mov $3,%eax
    mov $5,%edi
    syscall
    test %rax,%rax
    js failed
    lea python_path(%rip),%rdi
    mov %rdi,8(%r12)
    lea 8(%r12),%rsi
    mov (%r12),%rdx
    lea 16(%r12,%rdx,8),%rdx
    mov $59,%eax
    syscall
failed:
    mov $125,%edi
    mov $60,%eax
    syscall
    ud2
check_lifeline:
    movw $0,6(%r14)
    mov %r14,%rdi
    mov $1,%esi
    xor %edx,%edx
    mov $7,%eax
    syscall
    test %rax,%rax
    jne failed
    ret
python_path:
