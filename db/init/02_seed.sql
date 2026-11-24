-- Sample data. All people, numbers and IDs are fictional.
INSERT INTO employees VALUES
('E107','Meera Joshi','IT','IT Manager',NULL,'Noida','full_time','2018-09-03','meera.joshi@acme-corp.example','+91 98111 34343','meera.joshi@proton.me','GHJPJ6789R','12312312312312',3100000),
('E108','Vikram Rao','Finance','Finance Director',NULL,'Mumbai','full_time','2017-05-22','vikram.rao@acme-corp.example','+91 98330 56565','vikram.rao.home@gmail.com','HKLPR1122S','45645645645645',5500000),
('E103','Priya Nair','Human Resources','HR Business Partner',NULL,'Bengaluru','full_time','2020-01-20','priya.nair@acme-corp.example','+91 99001 44556','priya.nair.home@gmail.com','CQNPN9012M','30210045678912',1900000),
('E101','Ananya Sharma','Engineering','Engineering Manager','E107','Noida','full_time','2019-04-01','ananya.sharma@acme-corp.example','+91 98110 23456','ananya.s.personal@gmail.com','ABCPS1234K','50100012345678',4200000),
('E102','Rohan Verma','Engineering','Senior Software Engineer','E101','Noida','full_time','2021-07-12','rohan.verma@acme-corp.example','+91 98730 11223','rohanv92@yahoo.com','BXRPV5678L','50100087654321',2600000),
('E104','Arjun Mehta','IT','IT Support Specialist','E107','Noida','full_time','2022-03-14','arjun.mehta@acme-corp.example','+91 97170 66778','arjun.m@outlook.com','DLMPM3456N','91201011122233',1100000),
('E105','Sneha Iyer','Finance','Financial Analyst','E108','Mumbai','full_time','2023-02-06','sneha.iyer@acme-corp.example','+91 98200 99887','sneha.iyer.p@gmail.com','EKSPI7890P','00112233445566',1500000),
('E106','Karan Singh','Engineering','Software Engineer Intern','E101','Noida','intern','2026-06-01','karan.singh@acme-corp.example','+91 88000 12121','karan.s@gmail.com','FJKPS2345Q','77889900112233',360000),
('E109','Fatima Khan','Sales','Account Executive','E108','Delhi','contract','2025-11-10','fatima.khan@acme-corp.example','+91 99580 78787','fatima.k@gmail.com','JMNPK3344T','78978978978978',1300000),
('E110','David Thomas','Human Resources','Talent Acquisition Lead','E103','Bengaluru','full_time','2022-08-29','david.thomas@acme-corp.example','+91 90080 90909','david.t.home@gmail.com','KPQPT5566U','32132132132132',2000000);

-- Leave year 2026. Entitlements match policies/leave_policy.md
INSERT INTO leave_balances (employee_id, leave_year, leave_type, entitled_days, carried_forward, used_days, pending_days) VALUES
('E101',2026,'earned',18,10,12,0), ('E101',2026,'sick',10,0,2,0), ('E101',2026,'casual',7,0,5,0),
('E102',2026,'earned',18,6,9,2),   ('E102',2026,'sick',10,0,4,0), ('E102',2026,'casual',7,0,3,1),
('E103',2026,'earned',18,8,15,0),  ('E103',2026,'sick',10,0,1,0), ('E103',2026,'casual',7,0,6,0),
('E104',2026,'earned',18,3,7,0),   ('E104',2026,'sick',10,0,6,0), ('E104',2026,'casual',7,0,2,0),
('E105',2026,'earned',18,0,4,3),   ('E105',2026,'sick',10,0,0,0), ('E105',2026,'casual',7,0,1,0),
('E105',2026,'parental',182,0,0,0),
('E106',2026,'earned',0,0,0,0),    ('E106',2026,'sick',5,0,1,0),  ('E106',2026,'casual',3,0,1,0),
('E107',2026,'earned',18,10,14,0), ('E107',2026,'sick',10,0,3,0), ('E107',2026,'casual',7,0,7,0),
('E108',2026,'earned',18,10,6,0),  ('E108',2026,'sick',10,0,0,0), ('E108',2026,'casual',7,0,2,0),
('E109',2026,'earned',12,0,5,0),   ('E109',2026,'sick',6,0,2,0),  ('E109',2026,'casual',4,0,0,0),
('E110',2026,'earned',18,5,11,0),  ('E110',2026,'sick',10,0,5,0), ('E110',2026,'casual',7,0,4,0);

INSERT INTO it_assets VALUES
('AST-1001','laptop','Lenovo ThinkPad T14 Gen 3','PF3ABC01','E101','2023-01-10','2023-01-05','2026-01-04','in_use'),
('AST-1002','laptop','Apple MacBook Pro 14 M2','C02XYZ0002','E102','2023-05-15','2023-05-01','2026-04-30','in_use'),
('AST-1003','monitor','Dell U2723QE 27in','CN0DELL003','E102','2023-05-15','2023-05-01','2026-04-30','in_use'),
('AST-1004','yubikey','YubiKey 5C NFC','YK5C000004','E102','2024-02-01','2024-01-20','2029-01-19','in_use'),
('AST-1005','laptop','Dell Latitude 7440','DL7440005','E103','2024-03-01','2024-02-20','2027-02-19','in_use'),
('AST-1006','laptop','Lenovo ThinkPad X1 Carbon Gen 9','PF3ABC06','E104','2022-03-14','2021-11-30','2024-11-29','in_use'),
('AST-1007','headset','Jabra Evolve2 65','JB650007','E104','2022-03-14','2022-02-01','2024-01-31','in_use'),
('AST-1008','laptop','HP EliteBook 840 G8','HP840G8008','E105','2023-02-06','2021-06-15','2024-06-14','in_repair'),
('AST-1009','laptop','Dell Latitude 5440 (loaner)','DL5440009','E105','2026-10-28','2024-01-10','2027-01-09','in_use'),
('AST-1010','laptop','Apple MacBook Air M3','C02XYZ0010','E106','2026-06-01','2026-05-20','2029-05-19','in_use'),
('AST-1011','phone','iPhone 15','F2LX00011','E107','2024-09-25','2024-09-20','2025-09-19','in_use'),
('AST-1012','laptop','Apple MacBook Pro 16 M3','C02XYZ0012','E107','2024-01-15','2024-01-08','2027-01-07','in_use'),
('AST-1013','laptop','Lenovo ThinkPad T14s','PF3ABC13','E108','2025-04-01','2025-03-25','2028-03-24','in_use'),
('AST-1014','laptop','Dell Latitude 5440','DL5440014','E109','2025-11-10','2025-10-01','2028-09-30','in_use'),
('AST-1015','laptop','Lenovo ThinkPad T14 Gen 2','PF3ABC15','E110','2022-08-29','2021-08-01','2024-07-31','lost'),
('AST-1016','laptop','Lenovo ThinkPad T14 Gen 4','PF3ABC16','E110','2025-09-12','2025-09-01','2028-08-31','in_use'),
('AST-1017','laptop','Dell Latitude 7440','DL7440017',NULL,NULL,'2025-12-01','2028-11-30','in_stock');
