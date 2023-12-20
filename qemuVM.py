import os , time , sys
import subprocess , signal
import paramiko
import shutil
from libs.locallibs import ssh_cmd , mugen_log , sftp


class QemuVM(object):
    def __init__(self, vcpu,memory,workingDir,bkfile,
                 kernel,bios,initrd,pflash,arch='riscv64',
                 id=1,user='root',password='openEuler12#$',
                 path='/root/mugen' , restore=True,sharedir='',
                 qemuOption='' , screen=False):
        self.arch = arch
        self.id = id
        self.port , self.ip , self.user , self.password  = None , '127.0.0.1' , user , password
        self.vcpu , self.memory= vcpu , memory
        self.workingDir , self.bkFile = workingDir , bkfile
        self.kernel, self.kparms, self.initrd, self.bios, self.pflash = kernel, kparms, initrd, bios, pflash
        self.drive = 'img'+str(self.id)+'.qcow2'
        self.path = path
        self.restore = restore
        self.tapls = []
        self.sharedir = sharedir
        self.qemu_option = qemuOption
        self.screen = screen
        self.name = "mugenss"+str(self.id)
        if self.workingDir[-1] != '/':
            self.workingDir += '/'

    def findAvalPort(self , num=1):
        port_list = []
        port = 12055

        if shutil.which('lsof') is not None:
            pre_cmd = 'lsof -i :'
        elif shutil.which('netstat') is not None and sys.platform == 'linux':
            pre_cmd = 'netstat -anp 2>&1 | grep '
        else:
            sys.exit('Cannot find lsof or netstat command!')

        while len(port_list) != num:
            if os.system(pre_cmd + str(port) + ' > /dev/null') != 0:
                port_list.append(port)

            port += 1

        return port_list

    def ssh_exec(self,cmd,timeout=5):
        conn = paramiko.SSHClient()
        conn.set_missing_host_key_policy(paramiko.AutoAddPolicy)
        try:
            conn.connect(self.ip,self.port,self.user,self.password,timeout=timeout,allow_agent=False,look_for_keys=False)
            exitcode,output = ssh_cmd.pssh_cmd(conn,cmd)
            ssh_cmd.pssh_close(conn)
        except :
            mugen_log.logging("error" , "ssh execute "+cmd+" failed")
            exitcode , output = None , None
        return exitcode,output

    def sftp_get(self,remotedir,remotefile,localdir,timeout=5):
        conn = paramiko.SSHClient()
        conn.set_missing_host_key_policy(paramiko.AutoAddPolicy)
        conn.connect(self.ip,self.port,self.user,self.password,timeout=timeout,allow_agent=False,look_for_keys=False)
        sftp.psftp_get(conn,remotedir,remotefile,localdir)

    def sftp_put(self,localdir,localfile,remotedir,timeout=5):
        conn = paramiko.SSHClient()
        conn.set_missing_host_key_policy(paramiko.AutoAddPolicy)
        conn.connect(self.ip,self.port,self.user,self.password,timeout=timeout,allow_agent=False,look_for_keys=False)
        sftp.psftp_put(conn,localdir,localfile,remotedir)


    def start(self , disk=[] , machine=1 , tap_number=0 , taplist=[]):
        self.tapls = taplist
        if self.drive in os.listdir(self.workingDir):
            os.system('rm -f '+self.workingDir+self.drive)
        if self.restore:
            cmd = 'qemu-img create -f qcow2 -F qcow2 -b '+self.workingDir+self.bkFile+' '+self.workingDir+self.drive+" >/dev/null"
            res = os.system(cmd)
            if res != 0:
                print('Failed to create cow img: '+self.drive)
                return -1
        os.system('rm -f '+self.workingDir+'disk'+str(self.id)+'-*')
        if len(disk) > 0:
            for i in range(len(disk)):
                cmd = 'qemu-img create -f qcow2 '+self.workingDir+"disk"+str(self.id)+'-'+str(i+1)+'.qcow2 '+str(disk[i])+"G >/dev/null"
                res = os.system(cmd)
                if res != 0:
                    print('Failed to create img: disk'+str(id)+'-'+str(i+1))
                    exit(-1)


        ## Configuration
        cmdlist = ['qemu-system-'+self.arch ,
                   '-nographic' ,
                   '-smp' ,  str(self.vcpu) ,  '-m' , str(self.memory)+'G',
                   '-object' , 'rng-random,filename=/dev/urandom,id=rng0',
                   '-device' , 'virtio-rng-pci,rng=rng0' ]

        ## specity the drive file
        cmdlist.append('-drive')
        if self.restore:
            cmdlist.append("file="+self.workingDir+self.drive+",format=qcow2,if=virtio,id=hd0")
        else:
            cmdlist.append("file="+self.workingDir+self.bkFile+",format=qcow2,if=virtio,id=hd0")


        ## specity the bootloader option
        if self.kernel is not None:
            cmdlist.extend(['-kernel' , self.workingDir+self.kernel])

        if self.bios is not None:
            cmdlist.append('-bios')
            if self.bios == 'none':
                cmdlist.append(self.bios)
            else:
                cmdlist.append(self.workingDir+self.bios)
        if self.initrd is not None:
            cmdlist.extend(['-initrd' , self.workingDir+self.initrd])

        if self.pflash is not None:
            self.npflash = self.workingDir+"/OVMF_"+str(self.id)+".fd"
            os.system(f'/bin/cp -rf {self.pflash} {self.npflash}')
            cmdlist.extend(['-drive' , f'if=pflash,format=raw,file={self.npflash}'])

        ## specity the append option
        if self.sharedir != '' and self.arch == 'riscv64':
            shared_path=self.workingDir+self.sharedir+str(self.id)
            os.system("mkdir "+shared_path)
            cmdlist.extend(["-virtfs" , "local,id=test,path="+shared_path+",security_model=none,mount_tag=test"])

        if len(disk) > 0:
            for i in range(len(disk)):
                cmdlist.extend(["-drive", "file="+self.workingDir+"disk"+str(self.id)+'-'+str(i+1)+".qcow2,format=qcow2,if=virtio,id=hd"+str(i+1)])

        if tap_number > 0:
            if machine > 1:
                tap_number -= 1
                used_tap = taplist[-1]
                mac = int(used_tap.strip('tap'))
                cmdlist.extend(["-netdev", "tap,id=net"+used_tap+",ifname="+used_tap+",script=no,downscript=no",
                                "-device", "virtio-net-pci,netdev=net"+used_tap+",mac=52:54:00:11:45:{:0>2d}".format(mac+1)])

            for i in range(tap_number):
                used_tap = taplist[i]
                mac = int(used_tap.strip('tap'))
                cmdlist.extend(["-netdev","tap,id=net"+used_tap+",ifname="+used_tap+",script=no,downscript=no",
                                "-device", "virtio-net-pci,netdev=net"+used_tap+",mac=52:54:00:11:45:{:0>2d}".format(mac+1)])


        self.port = self.findAvalPort(1)[0]
        cmdlist.extend(["-netdev" , "user,id=usernet,hostfwd=tcp::"+str(self.port)+"-:22",
                        "-device" , "virtio-net-pci,netdev=usernet"])

        if self.qemu_option is not None:
            cmdlist.append(self.qemu_option)

        cmd = " ".join(cmdlist)

        if self.screen:
            if os.system("screen -ls | grep "+self.name+" >/dev/null") == 0:
                os.system("screen -X -S "+self.name+" quit")
            os.system("screen -S "+self.name+" -d -m "+cmd)
            time.sleep(1)
            if os.system("screen -ls | grep "+self.name+" >/dev/null") != 0:
                print("Qemu process terminate unexpectedly " + cmd)
            else:
                print("Qemu process is running with cmdline " + cmd)
        else:
            self.process = subprocess.Popen(args=cmd,stderr=subprocess.PIPE,stdout=subprocess.PIPE,stdin=subprocess.PIPE,encoding='utf-8',shell=True)
            time.sleep(1)
            ret = self.process.poll()
            if ret is not None:
                print("Qemu process terminate unexpectedly " + str(ret))
                print(self.process.communicate())
            else:
                print("Qemu process is running with cmdline " + cmd)


    def sharedReady(self):
        if self.sharedir != '' and self.arch == 'riscv64':
            while not os.path.exists(self.workingDir+self.sharedir+str(self.id)+'/shared_ready'):
                time.sleep(5)
            os.system('rm -rf '+self.workingDir+self.sharedir+'/shared_ready')

    def waitReady(self):
        conn = 519
        while conn == 519:
            con = paramiko.SSHClient()
            con.set_missing_host_key_policy(paramiko.AutoAddPolicy)
            try:
                conn=0
                time.sleep(5)
                con.connect(self.ip, self.port, self.user, self.password, timeout=5)
            except Exception as e:
                conn = 519
        if conn != 519:
            con.close()

    def conftap(self , br_ip , tapnode=None):
        self.tapip = '.'.join(br_ip.split(".")[:-1]+[str(self.id+1)])
        print(self.ssh_exec('dnf install lshw -y')[1])
        nic = self.ssh_exec("lshw -class network | grep -A 5 'description: Ethernet interface' | grep 'logical name:' | awk '{print $NF}' | grep -v 'lo'")[1].split("\n")[0]
        print("config the machine "+str(self.id)+" nic name "+nic)
        print(self.ssh_exec(f"nmcli c a type Ethernet con-name {nic} ifname {nic} ip4 {self.tapip}/24" , timeout=300)[1])
        print(self.ssh_exec("nmcli c m "+nic+" ipv4.address "+self.tapip+"/24" , timeout=300)[1])
        # print(self.ssh_exec("nmcli c m "+nic+" ipv4.gateway "+br_ip , timeout=300)[1])
        print(self.ssh_exec("nmcli c m "+nic+" ipv4.method manual",timeout=300)[1])
        print(self.ssh_exec("nmcli c up "+nic , timeout=300)[1])
        print(self.ssh_exec("rm -rf "+self.path+"/conf",timeout=300)[1])
        print(self.ssh_exec('bash '+self.path+'/mugen.sh -c --user root --password openEuler12#$ --ip '+self.tapip+' 2>&1',timeout=300)[1])
        if tapnode is not None:
            for ip in tapnode:
                print(self.ssh_exec('bash '+self.path+'/mugen.sh -c --user root --password openEuler12#$ --ip '+ip+' 2>&1',timeout=300)[1])


    def isBroken(self):
        conn = 519
        while conn == 519:
            con = paramiko.SSHClient()
            con.set_missing_host_key_policy(paramiko.AutoAddPolicy)
            try:
                conn = 0
                con.connect(self.ip, self.port, self.user, self.password, timeout=5)
            except Exception as e:
                conn = 519
                return True
        if conn != 519:
            con.close()
        return False

    def waitPoweroff(self):
        if self.screen:
            while os.system("screen -ls | grep "+self.name+" >/dev/null") == 0:
                time.sleep(1)
        else:
            wait_time = 0
            while self.process.poll() is None:
                wait_time += 1
                time.sleep(1)
                if wait_time > 60:
                    self.process.terminate()
            while os.system('netstat -anp 2>&1 | grep '+str(self.port)+' > /dev/null') == 0:
                time.sleep(1)

    def destroy(self):
        if self.isBroken() and not self.screen:
            try:
                self.process.terminate()
            except:
                mugen_log.logging('ERROR' , 'kill '+str(self.process.pid)+' false')
        else:
            self.ssh_exec('poweroff')
        if self.restore:
            os.system('rm -f '+self.workingDir+self.drive)
        os.system('rm -f '+self.workingDir+'disk'+str(self.id)+'-*')
        if self.sharedir != '':
            os.system('rm -rf '+self.workingDir+self.sharedir+str(self.id))
        if self.pflash is not None:
            os.system(f"rm -f {self.npflash}")
