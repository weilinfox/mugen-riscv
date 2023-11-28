from dataclasses import replace
import os
import argparse
from socket import timeout
import time
import paramiko
from libs.locallibs.mugen_riscv import TestEnv,TestTarget
from queue import Queue
from libs.locallibs import sftp,ssh_cmd,mugen_log
from threading import Thread
import json
from qemuVM import QemuVM
from combination_parser import combination


def lstat(qemuVM:QemuVM,remotepath,timeout=5):
    conn = paramiko.SSHClient()
    conn.set_missing_host_key_policy(paramiko.AutoAddPolicy)
    conn.connect(qemuVM.ip,qemuVM.port,qemuVM.user,qemuVM.password,timeout=timeout,allow_agent=False,look_for_keys=False)
    try:
        stat = paramiko.SFTPClient.from_transport(conn.get_transport()).lstat(remotepath)
    except:
        stat = None
    else:
        if stat.st_size == 0:
            stat = None
    finally:
        ssh_cmd.pssh_close(conn)
    return stat


def copydown(copydir , copyfile='' , localdir = '.',timeout=5) -> bool :
    if copyfile == '':
        target = copydir
    else:
        target = os.path.join(copydir,copyfile)
    os.system('ls '+localdir+' >/dev/null || mkdir -p '+localdir)
    t_end = time.time() + timeout
    while time.time() < t_end:
        if os.path.exists(target):
            mugen_log.logging("info" , "start to copy "+target+' to '+localdir)
            os.system('/bin/cp -rf '+target+' '+localdir)
            return True
    return False

def runTest(qemuVM:QemuVM , testsuite , runArgs):
    if not qemuVM.isBroken():
        suite_name = None
        if testsuite.endswith('.json'):
            suite_name = '_'.join(testsuite.split('_')[:-1])
            qemuVM.sftp_put(qemuVM.workingDir+'splited_json/'+suite_name , testsuite , qemuVM.path)
            runArgs += f' -c {testsuite}'
        else:
            runArgs += ' -l list_temp'
        print(qemuVM.ssh_exec('cd '+qemuVM.path+' ; \
                               echo \''+testsuite+'\' > list_temp ; \
                               bash mugen_riscv.sh '+runArgs,timeout=60)[1])
        if not copydown(qemuVM.workingDir+qemuVM.sharedir+'/logs_failed' , '' , qemuVM.workingDir):
            if lstat(qemuVM,qemuVM.path+'/logs_failed') is not None:
                qemuVM.sftp_get(qemuVM.path+'/logs_failed','',qemuVM.workingDir)
        if not copydown(qemuVM.workingDir+qemuVM.sharedir+'/logs' , '' , qemuVM.workingDir):
            if lstat(qemuVM,qemuVM.path+'/logs') is not None:
                qemuVM.sftp_get(qemuVM.path+'/logs','',qemuVM.workingDir)
        if not copydown(qemuVM.workingDir+qemuVM.sharedir+'/suite2cases_out' , '' , qemuVM.workingDir):
            if lstat(qemuVM,qemuVM.path+'/suite2cases_out') is not None:
                qemuVM.sftp_get(qemuVM.path+'/suite2cases_out','',qemuVM.workingDir)
        if not copydown(qemuVM.workingDir+qemuVM.sharedir , 'exec.log' , qemuVM.workingDir+'exec_log/'+testsuite):
            qemuVM.sftp_get(qemuVM.path,'exec.log',qemuVM.workingDir+'exec_log/'+testsuite)
        if suite_name is not None and os.path.exists(qemuVM.workingDir+'logs/'+suite_name+'_0'):
            if not os.path.exists(f'{qemuVM.workingDir}logs/{suite_name}'):
                os.makedirs(f'{qemuVM.workingDir}logs/{suite_name}')
            os.system(f'/bin/cp -rf {qemuVM.workingDir}logs/{suite_name}_0/* {qemuVM.workingDir}logs/{suite_name}')
            os.system(f'rm -rf {qemuVM.workingDir}logs/{suite_name}_0 ')
        checkName = suite_name if suite_name is not None else testsuite
        assert os.path.exists(f'{qemuVM.workingDir}logs/{checkName}')
        if suite_name is not None:
            os.system(f'rm -rf {qemuVM.workingDir}splited_json/{suite_name}/{testsuite}')

        

class Dispatcher(Thread):
    def __init__(self,qemuVM:QemuVM,targetQueue:Queue,tapQueue:Queue,br_ip,step,runArg,initTarget=None):
        super(Dispatcher,self).__init__()
        self.qemuVM = qemuVM
        self.targetQueue = targetQueue
        self.initTarget = initTarget
        self.tapQueue = tapQueue
        self.step = step
        self.br_ip = br_ip
        self.runArg = runArg
        self.attachVM = []

    def run(self):
        notEmpty = True
        while notEmpty:
            target = None
            if self.initTarget is not None:
                target = self.initTarget
                self.initTarget = None
            else:
                try:
                    target = self.targetQueue.get(block=True,timeout=2)
                except:
                    break

            tapnum , eachnum = 0 , 0
            if target[2] > 1 and self.runArg.find('multiMachine') != -1:
                if target[3] > 0 and self.runArg.find('addNic') != -1:
                    tapnum = target[2]*(target[3]+1)
                    eachnum = target[3]+1
                else:
                    tapnum = target[2]
                    eachnum = 1
            else:
                if target[3] > 0 and self.runArg.find('addNic') != -1:
                    tapnum = target[3]
                    eachnum = tapnum

            if tapnum > self.tapQueue.qsize():
                self.targetQueue.put(target)
            else:
                self.qemuVM.start(disk=target[1],machine=target[2],tap_number=eachnum,taplist=[self.tapQueue.get() for i in range(eachnum)])
                #self.qemuVM.sharedReady()
                self.qemuVM.waitReady()
                for i in range(1 , target[2]):
                    self.attachVM.append(QemuVM(id= i*self.step+self.qemuVM.id, vcpu=self.qemuVM.vcpu , memory=self.qemuVM.memory,
                                                user=self.qemuVM.user , password=self.qemuVM.password,
                                                kernel=self.qemuVM.kernel , bios=self.qemuVM.bios ,  initrd=self.qemuVM.initrd, pflash=self.qemuVM.pflash,
                                                arch=self.qemuVM.arch , qemuOption=self.qemuVM.qemu_option,
                                                workingDir=self.qemuVM.workingDir , bkfile=self.qemuVM.bkFile , path=self.qemuVM.path, screen=self.qemuVM.screen
                                                ))
                    self.attachVM[i-1].start(disk=target[1],machine=target[2],tap_number=eachnum,taplist=[self.tapQueue.get() for i in range(eachnum)])
                    self.attachVM[i-1].waitReady()
                    self.attachVM[i-1].conftap(br_ip = self.br_ip)
                if target[2] > 1 and self.runArg.find('multiMachine') != -1:
                    self.qemuVM.conftap(br_ip = self.br_ip , tapnode = ['.'.join(self.br_ip.split(".")[:-1]+[str(self.attachVM[i].id+1)]) for i in range(target[2]-1)])
                try:
                    runTest(self.qemuVM , target[0] , self.runArg)
                except:
                    target[4] += 1
                    mugen_log.logging("ERROR" , f"run test {target[0]} false with {target[4]} times")
                    if target[4] > 3:
                        mugen_log.logging("ERROR" , f"run test {target[0]} fail")
                    else:
                        self.targetQueue.put(target)
                self.qemuVM.destroy()
                self.qemuVM.waitPoweroff()
                while len(self.qemuVM.tapls) > 0:
                    self.tapQueue.put(self.qemuVM.tapls.pop())
                while len(self.attachVM) > 0:
                    self.attachVM[-1].destroy()
                    self.attachVM[-1].waitPoweroff()
                    while len(self.attachVM[-1].tapls) > 0:
                        self.tapQueue.put(self.attachVM[-1].tapls.pop())
                    self.attachVM.pop()
            


        

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-l',metavar='list_file',help='Specify the test targets list',dest='list_file')
    parser.add_argument('-x',type=int,default=1,help='Specify threads num, default is 1')
    parser.add_argument('-c',type=int,default=4,help='Specify virtual machine cores num, default is 4')
    parser.add_argument('-M',type=int,default=4,help='Specify virtual machine memory size(GB), default is 4 GB')
    parser.add_argument('-w',type=str,help='Specify working directory')
    parser.add_argument('-m','--mugen',action='store_true',help='Run native mugen test suites')
    parser.add_argument('--user',type=str,default=None,help='Specify user')
    parser.add_argument('--password',type=str,default=None,help='Specify password')
    parser.add_argument('-B',type=str,help='Specify bios')
    parser.add_argument('-K',type=str,help='Specify kernel')
    parser.add_argument('-U',type=str,help='Specify UEFI pflash')
    parser.add_argument('-D',type=str,help='Specify backing file name')
    parser.add_argument('-d',type=str,help='Specity mugen installed directory',dest='mugenDir')
    parser.add_argument('-g','--generate',action='store_true',default=False,help='Generate testsuite json after running test')
    parser.add_argument('--detailed',action='store_true',default=False,help='Print detailed log')
    parser.add_argument('--addDisk',action='store_true',default=False)
    parser.add_argument('--multiMachine',action='store_true',default=False)
    parser.add_argument('--addNic',action='store_true',default=False)
    parser.add_argument('--bridge_ip' , type=str , help='Specity the network bridge ip')
    parser.add_argument('-t',type=int,default=0,help='Specity the number of generated free tap')
    parser.add_argument('--qemu_option',type=str,default='',help='qemu option in command line')
    parser.add_argument('-a',type=str,default='riscv64',help='specity the qemu arch')
    parser.add_argument('-initrd',type=str,help='Specity the initrd file')
    parser.add_argument('--mirror',type=str,default='https://gitee.com/openeuler/mugen.git',help='Specity the mugen mirror')
    parser.add_argument('--screen',action='store_true',default=False,help='Use screen command to manage qemu processes')
    parser.add_argument('-F',type=str,help='Specify test config file')
    args = parser.parse_args()

    test_env = TestEnv()
    test_env.ClearEnv()
    test_env.PrintSuiteNum()

    # set default values
    threadNum = 1
    coreNum , memSize = 4 , 4
    runningArg = ''
    mugenNative , generateJson , preImg , genList = False , False , False , False
    list_file , workingDir , bkFile , orgDrive , mugenPath = None , None , None , None , None
    kernel , bios , initrd , pflash = None , None , None , None
    img_base = 'img_base.qcow2'
    detailed = False
    user , password = "root","openEuler12#$"
    addDisk, multiMachine, addNic = False,False,False
    screen = False
    qemu_option , qemu_arch = '' , 'riscv64'
    bridge_ip = None
    tap = Queue()
    mirror='https://gitee.com/openeuler/mugen.git'
    

    # parse arguments
    if args.F is not None:
        configFile = open(args.F,'r')
        configData = json.loads(configFile.read())
        if configData.__contains__('threads'):
            if type(configData['threads']) == int and configData['threads'] > 0:
                threadNum = configData['threads']
            else:
                print('Thread number is invalid!')
                exit(-1)
        if configData.__contains__('cores'):
            if type(configData['cores']) == int and configData['cores'] > 0:
                coreNum = configData['cores']
            else:
                print('Core number is invalid!')
                exit(-1)
        if configData.__contains__('memory'):
            if type(configData['memory']) == int and configData['memory'] > 0:
                memSize = configData['memory']
            else:
                print('Memory size is invalid!')
                exit(-1)
        if configData.__contains__('user'):
            if type(configData['user']) == str:
                user = configData['user']
            else:
                print('user is invalid!')
                exit(-1)
        if configData.__contains__('password'):
            if type(configData['password']) == str:
                password = configData['password']
            else:
                print('password is invalid!')
                exit(-1)
        if configData.__contains__('addDisk') and configData['addDisk'] == 1:
            runningArg += " --addDisk"
        if configData.__contains__('multiMachine') and configData['multiMachine'] == 1:
            runningArg += " --multiMachine"
        if configData.__contains__('addNic') and configData['addNic'] == 1:
            runningArg += " --addNic"
        if configData.__contains__('mugenNative') and configData['mugenNative'] == 1:
            runningArg += " -m"
            mugenNative = True
        if configData.__contains__('generate') and configData['generate'] == 1:
            runningArg += " -g"
        if configData.__contains__('detailed') and configData['detailed'] == 1:
            runningArg += " -x"
        if configData.__contains__('bridge ip'):
            bridge_ip = configData['bridge ip']
        if configData.__contains__('qemu option') and type(configData['qemu option'])==str:
            qemu_option = configData['qemu option']
        if configData.__contains__('qemu arch') and type(configData['qemu arch'])==str:
            qemu_arch = configData['qemu arch']
        if configData.__contains__('initrd') and type(configData['initrd'])==str:
            initrd = configData['initrd']
        if configData.__contains__('useScreen') and configData['useScreen'] == 1:
            screen = True
        if configData.__contains__('mirror') and type(configData['mirror']) == str:
            mirror = configData['mirror']
        if configData.__contains__('tap num') and type(configData['tap num'])==int:
            for i in range(configData['tap num']):
                tap.put('tap'+str(i))
        if configData.__contains__('workingDir') and (configData.__contains__('bios') or configData.__contains__('kernel')) and configData.__contains__('drive'):
            if configData.__contains__('bios') and type(configData['bios']) == str:
                bios = configData['bios']
            if configData.__contains__('kernel') and type(configData['kernel']) == str:
                kernel = configData['kernel']
            if configData.__contains__('pflash') and type(configData['pflash']) == str:
                pflash = configData['pflash']
            if type(configData['workingDir']) == str:
                workingDir = configData['workingDir']
            else:
                print('Invalid working directory!')
                exit(-1)
            if type(configData['drive']) == str:
                orgDrive = configData['drive']
            else:
                print('Invalid drive file!')
                exit(-1)
            if configData.__contains__('mugenDir'):
                preImg = False
                bkFile = orgDrive
                mugenPath = configData['mugenDir'].rstrip('/')
                if configData.__contains__('listFile') and type(configData['listFile']) == str:
                    list_file = configData['listFile']
                    genList = False
                else:
                    genList = True
            else:
                preImg = True
                bkFile = img_base
                mugenPath = "/root/mugen"
                if configData.__contains__('listFile') and type(configData['listFile']) == str:
                    list_file = configData['listFile']
                    genList = False
                else:
                    genList = True
        else:
            print('Please specify working directory and bios or kernel and drive file!')
            exit(-1)
    else:
        if args.x > 0:
            threadNum = args.x
        else:
            print('Thread number is invalid!')
            exit(-1)
        if args.c > 0:
            coreNum = args.c
        else:
            print('Core number is invalid!')
            exit(-1)
        if args.M > 0:
            memSize = args.M
        else:
            print('Memory size is invalid!')
            exit(-1)
        if args.user is not None:
            user = args.user
        if args.password is not None:
            password = args.password
        if args.addDisk:
            runningArg += ' --addDisk'
        if args.multiMachine:
            runningArg += ' --multiMachine'
        if args.addNic:
            runningArg += ' --addNic'
        if args.mugen:
            runningArg += ' -m'
            mugenNative = True
        if args.generate:
            runningArg += ' -g'
        if args.detailed:
            runningArg += ' -x'      
        if args.bridge_ip:
            bridge_ip = args.bridge_ip
        if args.mirror:
            mirror = args.mirror
        if args.t > 0:
            for i in range(args.t):
                tap.put('tap'+str(i))
        if args.a:
            qemu_arch = args.a
        if args.qemu_option:
            qemu_option=args.qemu_option
        if args.initrd:
            initrd=args.initrd
        if args.screen:
            screen = True

        if args.w != None and (args.B != None or args.K !=None) and args.D != None:
            workingDir = args.w
            orgDrive = args.D
            bios = args.B
            kernel = args.K
            pflash = args.U
            if args.mugenDir != None:
                preImg = False
                bkFile = orgDrive
                mugenPath = args.mugenDir.rstrip('/')
                if args.list_file != None:
                    list_file = args.list_file
                    genList = False
                else:
                    genList = True
            else:
                preImg = True
                bkFile = img_base
                mugenPath = "/root/mugen"
                if args.list_file != None:
                    list_file = args.list_file
                    genList = False
                else:
                    genList = True
        else:
            print('Please specify working directory and bios or kernel and drive file!')
            exit(-1)

    if preImg == True or genList == True:
        if preImg == True and (bkFile not in os.listdir(workingDir)):
            res = os.system('qemu-img create -f qcow2 -F qcow2 -b '+workingDir+orgDrive+' '+workingDir+bkFile)
            if res != 0:
                print('Failed to create img-base')
                exit(-1)

        preVM = QemuVM(id=1,user=user,password=password,
                       kernel=kernel,bios=bios,initrd=initrd,pflash=pflash,
                       vcpu=coreNum,memory=memSize,
                       path=mugenPath,workingDir=workingDir,bkfile=bkFile,restore=False,
                       qemuOption=qemu_option,arch=qemu_arch,sharedir='shared',screen=screen)
        preVM.start()
        preVM.waitReady()
        if preImg == True:
            print(preVM.ssh_exec('dnf install git -y',timeout=120)[1])
            print(preVM.ssh_exec('cd /root \n \
                                  git clone '+mirror,timeout=600)[1])
            print(preVM.ssh_exec('cd /root/mugen \n \
                                  bash dep_install.sh',timeout=300)[1])
            print(preVM.ssh_exec('cd /root/mugen \n \
                                  bash mugen.sh -c --port 22 --user root --password openEuler12#$ --ip 127.0.0.1 2>&1',timeout=300)[1])
            file=preVM.ssh_exec("if test -f /etc/rc.local; then \
                                    echo '/etc/rc.local';\
                                 elif test -f /etc/rc.d/rc.local; then \
                                    echo '/etc/rc.d/rc.local'; \
                                 else \
                                    ls /etc/rc.d || mkdir /etc/rc.d; \
                                    touch /etc/rc.d/rc.local; \
                                 fi")[1]
            preVM.ssh_exec('echo "ls /root/shared || mkdir /root/shared" >> '+file)
            preVM.ssh_exec('echo "rm -rf /root/shared/*" >> '+file)
            preVM.ssh_exec('echo "mount -t 9p -o trans=virtio,access=any test /root/shared" >> '+file)
            preVM.ssh_exec('echo "chmod 1777 /root/shared" >> '+file)
            preVM.ssh_exec('echo "touch /root/shared/shared_ready" >> '+file)
            preVM.ssh_exec('chmod a+x '+file)
            if lstat(preVM , '/root/mugen/mugen_riscv.py') is None:
                preVM.sftp_put('.' , 'mugen_riscv.py' , '/root/mugen')

        if genList is True:
            preVM.ssh_exec('dnf list | grep -E \'riscv64|noarch\' > pkgs.txt',timeout=120)
            preVM.sftp_get('.','pkgs.txt','.',timeout=5)
            pkgfile = open('pkgs.txt','r')
            raw = pkgfile.read()
            pkgfile.close()
            os.system('rm -f pkgs.txt')
            colums = raw.split('\n')
            pkgs = []
            for colum in colums:
                witharch = colum.split(' ')[0]
                witharch = witharch.replace('.riscv64','')
                pkgs.append(witharch.replace('.noarch',''))
            outputfile = open('list','w')
            pkgs.append('os-basic')
            pkgs.append('os-storage')
            for pkg in pkgs:
                outputfile.write(pkg+'\n')
            outputfile.close()
            list_file = 'list'
        preVM.destroy()
        preVM.waitPoweroff()

    if qemu_arch == 'riscv64':
        runningArg += ' -o /root/shared'


    if list_file is not None:
        test_target = TestTarget(list_file_name=list_file)
        test_target.PrintTargetNum()
        test_target.CheckTargets(suite_list_mugen=test_env.suite_list_mugen,suite_list_riscv=test_env.suite_list_riscv,mugen_native=mugenNative,qemu_mode=True)
        test_target.PrintUnavalTargets()
        test_target.PrintAvalTargets()

        qemuVM = []
        for i in range(threadNum):
            qemuVM.append(QemuVM(id=i , vcpu=coreNum , memory=memSize,
                                 user=user , password=password,
                                 kernel=kernel , bios=bios, initrd=initrd, pflash=pflash,
                                 arch=qemu_arch , qemuOption=qemu_option,
                                 workingDir=workingDir , bkfile=bkFile , path=mugenPath,
                                 sharedir='shared' , screen = screen))   
        targetQueue = Queue()
        combinations = combination()
        for target in test_target.test_list:
            jsondata = json.loads(open('suite2cases/'+target+'.json','r').read())
            caseNum = len(jsondata['cases'])
            if caseNum != 0:
                if caseNum > 20:
                    count , id = 0 , 0
                    os.system(f'ls {workingDir}splited_json/{target} || mkdir -p {workingDir}splited_json/{target}')
                    target_path = f'{workingDir}splited_json/{target}'
                    for case in jsondata['cases']:
                        combinations.add_case(target , case['name'])
                        count += 1
                        if count == 20:
                            combinations.export_one_json(target , target_path , id)
                            targetQueue.put([target+'_'+str(id)+'.json' , jsondata.get('add disk' , []) , jsondata.get("machine num" , 1) , jsondata.get("add network interface" , 0) , 0])
                            id += 1
                            count = 0
                            combinations.clear_one_testsuite(target)
                    combinations.export_one_json(target , target_path , id)
                    combinations.clear_one_testsuite(target)
                    targetQueue.put([target+'_'+str(id)+'.json' , jsondata.get('add disk' , []) , jsondata.get("machine num" , 1) , jsondata.get("add network interface" , 0) , 0])
                else:
                    targetQueue.put([target , jsondata.get('add disk' , []) , jsondata.get("machine num" , 1) , jsondata.get("add network interface" , 0) , 0])

        dispathcers = []
        for i in range(threadNum):
            dispathcers.append(Dispatcher(qemuVM=qemuVM[i] , targetQueue=targetQueue , tapQueue=tap , br_ip=bridge_ip , step = threadNum , runArg=runningArg))
            dispathcers[i].start()
            time.sleep(0.5)

        isAlive = True
        isEnd = False
        while isAlive:
            tempAlive = []
            for i in range(threadNum):
                if dispathcers[i].is_alive():
                    print('Thread '+str(i)+' is alive')
                    tempAlive.append(True)
                else:
                    print('Thread '+str(i)+' is dead')
                    while len(dispathcers[i].attachVM) > 0:
                        dispathcers[i].attachVM[-1].destroy()
                        dispathcers[i].attachVM[-1].waitPoweroff()
                        while len(dispathcers[i].attachVM[-1].tapls) > 0:
                            dispathcers[i].tapQueue.put(dispathcers[i].attachVM[-1].tapls.pop())
                        dispathcers[i].attachVM.pop()
                    while len(dispathcers[i].qemuVM.tapls) > 0:
                        dispathcers[i].tapQueue.put(dispathcers[i].qemuVM.tapls.pop())
                    tempAlive.append(False)
                    if not isEnd:
                        try:
                            target = targetQueue.get(block=True,timeout=2)
                        except:
                            isEnd = True
                        else:
                            dispathcers[i] = Dispatcher(qemuVM = qemuVM[i],targetQueue=targetQueue,initTarget=target , tapQueue=tap , br_ip=bridge_ip , step=threadNum , runArg=runningArg)
                            dispathcers[i].start()
            isAlive = False
            for i in range(threadNum):
                isAlive |= tempAlive[i]
            time.sleep(5)
    
    if genList is True:
        os.system('rm -f list')
            
